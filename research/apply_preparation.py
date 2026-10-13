"""전문자격 수집 원문을 보관하고 기존 기술자격 데이터와 준비 파일의 일치를 검사한다."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from backend.db.connection import database_connection
from backend.exam_schemas import ExamInformationInput
from backend.schemas import CertificateInput, ScheduleInput


ROOT = Path(__file__).resolve().parents[1]
PREPARATION = ROOT / 'research' / 'preparation'


def read_json(path: Path):
    """원본 JSON을 UTF-8로 읽는다."""
    return json.loads(path.read_text(encoding='utf-8'))


def read_verified_response(root: Path, attempt: dict) -> str:
    """보관한 원문이 수집 당시 해시와 일치할 때만 가져온다."""
    path = (root / attempt['response_file']).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('원문 경로가 보관 폴더 밖을 가리킵니다.')
    raw = path.read_bytes()
    # 이전 수집기의 write_text는 Windows에서 LF를 CRLF로 저장했다.
    # 원래 응답 해시와 저장 파일 해시가 달라도 줄바꿈만 복원해 일치해야 허용한다.
    normalized = raw.replace(b'\r\n', b'\n')
    if attempt['sha256'] not in (hashlib.sha256(raw).hexdigest(), hashlib.sha256(normalized).hexdigest()):
        raise ValueError(f'원문 해시 불일치: {attempt["response_file"]}')
    return raw.decode('utf-8')


def prepare_sources() -> list[dict]:
    """정상·빈 응답·실패 기록을 원문과 묶으며 실패를 정상 정보로 변환하지 않는다."""
    manifest = read_json(PREPARATION / 'source_manifest.json')
    for entry in manifest:
        if hashlib.sha256((ROOT / entry['path']).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f'보관 원본 목록의 해시 불일치: {entry["path"]}')
    collected = read_json(PREPARATION / 'professional_sources.json')
    if not collected['completed']:
        raise ValueError('수집 완료 기록이 필요합니다.')
    candidates = read_json(PREPARATION / 'professional_series_schedules.json')
    catalog = {row['qnet_code']: row for row in read_json(PREPARATION / 'catalog.json')}
    rows = []
    for source in collected['results']:
        attempts = source['attempts']
        latest = attempts[-1]
        retrieved_at = datetime.fromisoformat(latest['retrieved_at'])
        if retrieved_at.utcoffset() is None:
            raise ValueError('수집 시각에 시간대가 필요합니다.')
        if source['kind'] == 'details' and catalog[source['code']]['category'] != 'S':
            raise ValueError('전문자격 종목 코드가 아닙니다.')
        raw_responses = {}
        for attempt in attempts:
            if attempt.get('response_file'):
                raw_responses[attempt['response_file']] = read_verified_response(ROOT / 'research', attempt)
        payload = {'collection': source, 'raw_responses': raw_responses,
                   'review_status': 'unreviewed',
                   'schedule_candidates': [row for row in candidates
                                           if source['kind'] == 'schedules' and row['series_code'] == source['code']]}
        content_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        rows.append({'source_key': f'qnet-professional:{source["kind"]}:{source["code"]}',
                     'code': source['code'], 'kind': source['kind'], 'status': source['status'],
                     'source_url': latest['source_url'], 'retrieved_at': retrieved_at,
                     'payload': payload, 'content_sha256': content_hash})
    if len({(row['source_key'], row['retrieved_at']) for row in rows}) != len(rows):
        raise ValueError('같은 원본 수집 기록이 중복되었습니다.')
    return rows


def verify_existing_data(connection) -> dict:
    """DB의 실제 ID로 연결을 확인하고 준비 파일의 모든 모델 필드를 비교한다."""
    certificates = connection.execute('SELECT * FROM certificates').fetchall()
    schedules = connection.execute('SELECT * FROM schedules').fetchall()
    information = connection.execute('SELECT * FROM exam_information').fetchall()
    by_code = {row['qnet_code']: row for row in certificates}
    schedule_by_key = {(row['certificate_id'], row['round_key'], row['phase']): row for row in schedules}
    information_by_id = {row['certificate_id']: row for row in information}
    mismatches = []
    for row in read_json(PREPARATION / 'catalog.json'):
        expected = CertificateInput.model_validate({key: row[key] for key in CertificateInput.model_fields})
        actual = by_code.get(row['qnet_code'])
        actual_model = CertificateInput.model_validate({key: actual[key] for key in CertificateInput.model_fields}) if actual else None
        if actual_model is not None and actual_model.last_synced_at >= expected.last_synced_at:
            expected = expected.model_copy(update={'last_synced_at': actual_model.last_synced_at})
        if actual_model is None or expected != actual_model:
            mismatches.append({'kind': 'catalog', 'qnet_code': row['qnet_code']})
    for row in read_json(PREPARATION / 'technical_schedules.json'):
        values = {key: row[key] for key in ScheduleInput.model_fields if key in row}
        values['certificate_id'] = by_code[row['qnet_code']]['id']
        expected = ScheduleInput.model_validate(values)
        actual = schedule_by_key.get((expected.certificate_id, expected.round_key, expected.phase))
        if actual is None or expected != ScheduleInput.model_validate({key: actual[key] for key in ScheduleInput.model_fields}):
            mismatches.append({'kind': 'schedule', 'qnet_code': row['qnet_code'], 'round_key': expected.round_key, 'phase': expected.phase})
    for row in read_json(PREPARATION / 'technical_exam_information.json'):
        values = {**row['information'], 'certificate_id': by_code[row['qnet_code']]['id']}
        expected = ExamInformationInput.model_validate(values)
        actual = information_by_id.get(expected.certificate_id)
        if actual is None or expected != ExamInformationInput.model_validate({key: actual[key] for key in ExamInformationInput.model_fields}):
            mismatches.append({'kind': 'information', 'qnet_code': row['qnet_code']})
    return {'certificates': len(certificates), 'schedules': len(schedules),
            'exam_information': len(information), 'preparation_mismatches': mismatches}


def run(apply: bool) -> dict:
    """전체 원문을 검증한 뒤 한 트랜잭션으로 보관하고 별도 연결에서 결과를 확인한다."""
    rows = prepare_sources()
    with database_connection() as connection:
        before = verify_existing_data(connection)
        # 기존 DB를 덮어쓰지 않고 값이 다른 일정 후보를 원문 보관 테이블에 별도로 남긴다.
        if any(row['kind'] != 'schedule' for row in before['preparation_mismatches']):
            raise ValueError('종목 또는 상세정보가 다릅니다. 덮어쓰기 전에 확인이 필요합니다.')
        schedule_candidates = read_json(PREPARATION / 'technical_schedules.json')
        for difference in before['preparation_mismatches']:
            candidate = next(row for row in schedule_candidates if row['qnet_code'] == difference['qnet_code']
                             and row['round_key'] == difference['round_key'] and row['phase'] == difference['phase'])
            payload = {'schedule_candidate': candidate, 'review_status': 'needs_comparison',
                       'reason': '기존 DB와 일부 날짜·출처 정보가 달라 원문 후보로 보관합니다.'}
            rows.append({'source_key': f'qnet-technical:schedule:{candidate["qnet_code"]}:{candidate["round_key"]}:{candidate["phase"]}',
                         'qnet_code': candidate['qnet_code'], 'kind': 'schedules', 'code': None,
                         'status': 'fetched', 'source_url': candidate['source_url'],
                         'retrieved_at': datetime.fromisoformat(candidate['last_synced_at'].replace('Z', '+00:00')),
                         'payload': payload,
                         'content_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()})
        inserted = 0
        if apply:
            connection.execute((ROOT / 'backend/db/sources.sql').read_text(encoding='utf-8'))
            ids = {row['qnet_code']: row['id'] for row in connection.execute('SELECT id, qnet_code FROM certificates').fetchall()}
            existing_sources = {(row['source_key'], row['retrieved_at']): row for row in
                                connection.execute('SELECT source_key, retrieved_at, payload, content_sha256 FROM sources').fetchall()}
            for row in rows:
                existing = existing_sources.get((row['source_key'], row['retrieved_at']))
                if existing is not None:
                    if existing['payload'] != row['payload'] or existing['content_sha256'] != row['content_sha256']:
                        raise ValueError('같은 수집 시각의 기존 원문과 다릅니다. 전체 저장을 취소합니다.')
                    continue
                # 같은 수집 시각의 원문은 갱신하지 않고 새로운 수집만 별도 이력으로 보관한다.
                inserted += connection.execute('''INSERT INTO sources
                    (source_key, retrieved_at, certificate_id, series_code, kind, collection_status, source_url, payload, content_sha256)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (source_key, retrieved_at) DO NOTHING''',
                    (row['source_key'], row['retrieved_at'], ids[row['qnet_code']] if row.get('qnet_code') else ids[row['code']] if row['kind'] == 'details' else None,
                     row['code'] if row['kind'] == 'schedules' else None, row['kind'], row['status'],
                     row['source_url'], Jsonb(row['payload']), row['content_sha256'])).rowcount
                saved = connection.execute('SELECT payload, content_sha256 FROM sources WHERE source_key=%s AND retrieved_at=%s',
                                           (row['source_key'], row['retrieved_at'])).fetchone()
                if saved['payload'] != row['payload'] or saved['content_sha256'] != row['content_sha256']:
                    raise ValueError('같은 수집 시각의 기존 원문과 다릅니다. 전체 저장을 취소합니다.')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'database_applied': apply,
              'existing_data': before, 'prepared_sources': len(rows), 'inserted_sources': inserted}
    if apply:
        with database_connection() as connection:
            verified = 0
            saved_rows = {(row['source_key'], row['retrieved_at']): row for row in
                          connection.execute('SELECT source_key, retrieved_at, payload, content_sha256 FROM sources').fetchall()}
            for row in rows:
                saved = saved_rows.get((row['source_key'], row['retrieved_at']))
                if saved and saved['payload'] == row['payload'] and saved['content_sha256'] == row['content_sha256']:
                    verified += 1
            report['verified_sources'] = verified
            report['after'] = verify_existing_data(connection)
            report['source_counts'] = connection.execute('SELECT kind, collection_status, count(*) FROM sources GROUP BY kind, collection_status ORDER BY kind, collection_status').fetchall()
            if verified != len(rows) or report['after'] != before:
                raise ValueError('저장 후 검증이 일치하지 않습니다.')
    return report


def main() -> None:
    """기본은 검증만 하고 --apply를 지정할 때만 DB에 저장한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path, default=PREPARATION / 'DB_원문반영_결과.json')
    options = parser.parse_args()
    report = run(options.apply)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

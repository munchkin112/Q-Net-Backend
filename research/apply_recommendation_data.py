"""검토를 통과한 추천 자료만 별도 테이블에 저장하고 기존 자료 보존을 검사한다."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb
from backend.db.connection import database_connection

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'research/preparation/recommendation'
APPROVED_STATUSES = {'assistant_reviewed_summary_only', 'assistant_reviewed_summary_and_roles'}
PROTECTED_TABLES = ('certificates', 'exam_information', 'schedules', 'sources')


def get_content_hash(value: object) -> str:
    """키 순서를 통일해 같은 내용의 재실행을 구별한다."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def prepare_recommendation_data(approved: list[dict], original: list[dict], interests: list[dict]) -> tuple[list[dict], list[dict]]:
    """승인 상태·종목 연결·원문 해시·직업별 인용을 검사하고 저장할 값을 만든다."""
    by_code = {item['qnet_code']: item for item in original}
    if len(by_code) != len(original):
        raise ValueError('원본 종목 코드 중복')
    for item in original:
        for doc in item['career_evidence']:
            if (doc['qnet_code'] != item['qnet_code'] or doc['certificate_id'] != item['certificate_id']
                    or hashlib.sha256(doc['content'].encode('utf-8')).hexdigest() != doc['content_sha256']):
                raise ValueError('원문 연결 또는 해시 불일치')
    if {item['code'] for item in interests} != {f'{number:02}' for number in range(1, 25)} or len(interests) != 24:
        raise ValueError('관심 선택지 24개 필요')
    for interest in interests:
        if interest['classification_type'] != 'project_interest' or interest['is_official_ncs_certificate_mapping'] is not False:
            raise ValueError('공식 NCS 분류로 저장할 수 없음')
    rows = []
    seen = set()
    for item in approved:
        code = item['qnet_code']
        if code in seen or code not in by_code or item['review_status'] not in APPROVED_STATUSES or item['database_ready'] is not True:
            raise ValueError('중복·미확인·미승인 종목')
        seen.add(code)
        source = by_code[code]
        for key in ('certificate_id', 'name', 'category'):
            if item[key] != source[key]:
                raise ValueError('승인 자료 종목 식별 불일치')
        UUID(item['certificate_id'])
        if not item['summary'].strip() or item['interest_category_codes'] is not None:
            raise ValueError('요약 누락 또는 고정 분야 연결')
        docs = {doc['document_id']: doc for doc in source['career_evidence']}
        source_ids = set(item['summary_source_ids'])
        if not source_ids or not source_ids.issubset(docs):
            raise ValueError('요약 출처 누락 또는 다른 종목 근거')
        for evidence in item['summary_evidence']:
            if evidence['document_id'] not in source_ids or evidence['quote'] != docs[evidence['document_id']]['content']:
                raise ValueError('요약 인용 원문 불일치')
        for role in item['related_jobs']:
            role_ids = set(role['source_ids'])
            if not role_ids or not role_ids.issubset(docs) or not role['evidence_anchor'].strip():
                raise ValueError('직업 출처 누락 또는 다른 종목 근거')
            if not any(role['evidence_anchor'] in docs[identifier]['content'] for identifier in role_ids):
                raise ValueError('직업 인용 근거 없음')
            source_ids.update(role_ids)
        if item['related_jobs'] and item['review_status'] != 'assistant_reviewed_summary_and_roles':
            raise ValueError('미승인 직업 포함')
        evidence_documents = [doc for doc in source['career_evidence'] if doc['document_id'] in source_ids]
        for doc in evidence_documents:
            if not doc['source_url'] or datetime.fromisoformat(doc['retrieved_at']).utcoffset() is None:
                raise ValueError('원문 출처 또는 시간대 누락')
        # 모델 오류 기록은 로컬에 보관하고, 실제 사용 가능한 요약·근거만 DB에 제공한다.
        payload = {key: item[key] for key in ('certificate_id', 'qnet_code', 'name', 'category', 'summary',
                   'summary_source_ids', 'related_jobs', 'usage_restrictions', 'review_status', 'full_card_ready')}
        payload.update(evidence_documents=evidence_documents,
                       related_jobs_status='available' if item['related_jobs'] else 'unavailable_not_inferred',
                       usage_scope='duties_summary; not_eligibility_or_legal_authority',
                       interest_assignment_status='not_an_official_mapping')
        rows.append({'certificate_id': item['certificate_id'], 'qnet_code': code,
                     'payload': payload, 'content_sha256': get_content_hash(payload)})
    return rows, interests


def get_existing_data_snapshot(connection) -> dict:
    """기존 네 테이블을 읽기만 하며 전체 행의 건수와 내용 해시를 기록한다."""
    snapshot = {}
    for table in PROTECTED_TABLES:
        # 테이블명은 고정 상수만 사용한다. 사용자 입력을 SQL 문자열에 연결하지 않는다.
        rows = connection.execute(f'SELECT * FROM {table}').fetchall()
        hashes = sorted(get_content_hash(row) for row in rows)
        snapshot[table] = {'count': len(rows), 'sha256': get_content_hash(hashes)}
    return snapshot


def validate_database_identities(connection, rows: list[dict]) -> None:
    """코드와 UUID를 DB와 대조하고 다른 종목이면 저장하지 않는다."""
    by_code = {row['qnet_code']: row for row in connection.execute('SELECT id,qnet_code,name,category FROM certificates').fetchall()}
    for row in rows:
        actual = by_code.get(row['qnet_code'])
        if actual is None or str(actual['id']) != row['certificate_id']:
            raise ValueError('DB 종목 코드·UUID 불일치')
        if any(actual[key] != row['payload'][key] for key in ('name', 'category')):
            raise ValueError('DB 종목명·종류 불일치')


def upsert_recommendation_data(connection, rows: list[dict], interests: list[dict]) -> dict:
    """신규 또는 내용이 달라진 자료만 일괄 저장한다."""
    connection.execute((ROOT / 'backend/db/recommendation_data.sql').read_text(encoding='utf-8'))
    counts = {}
    batches = [
        ('recommendation_interest_categories', 'code',
         [{'code': item['code'], 'payload': item, 'content_sha256': get_content_hash(item)} for item in interests]),
        ('certificate_recommendation_contexts', 'certificate_id', rows),
    ]
    for table, primary_key, items in batches:
        existing = {str(row[primary_key]): row['content_sha256'] for row in
                    connection.execute(f'SELECT {primary_key},content_sha256 FROM {table}').fetchall()}
        counts[table] = {'inserted': 0, 'updated': 0, 'unchanged': 0}
        for item in items:
            previous = existing.get(item[primary_key])
            action = 'inserted' if previous is None else 'unchanged' if previous == item['content_sha256'] else 'updated'
            counts[table][action] += 1
        if table == 'certificate_recommendation_contexts':
            # ON CONFLICT는 기존 주키 행을 갱신한다. 내용이 같으면 갱신 시각도 유지한다.
            sql = '''INSERT INTO certificate_recommendation_contexts (certificate_id,qnet_code,payload,content_sha256)
                VALUES (%s,%s,%s,%s) ON CONFLICT (certificate_id) DO UPDATE
                SET qnet_code=EXCLUDED.qnet_code,payload=EXCLUDED.payload,
                    content_sha256=EXCLUDED.content_sha256,updated_at=now()
                WHERE certificate_recommendation_contexts.content_sha256 <> EXCLUDED.content_sha256'''
            values = [(item['certificate_id'], item['qnet_code'], Jsonb(item['payload']), item['content_sha256']) for item in items]
        else:
            sql = '''INSERT INTO recommendation_interest_categories (code,payload,content_sha256)
                VALUES (%s,%s,%s) ON CONFLICT (code) DO UPDATE
                SET payload=EXCLUDED.payload,content_sha256=EXCLUDED.content_sha256,updated_at=now()
                WHERE recommendation_interest_categories.content_sha256 <> EXCLUDED.content_sha256'''
            values = [(item['code'], Jsonb(item['payload']), item['content_sha256']) for item in items]
        with connection.cursor() as cursor:
            cursor.executemany(sql, values)
    return counts


def verify_database_results(connection, rows: list[dict], interests: list[dict]) -> dict:
    """전체 자료를 읽어 저장된 JSON이 입력과 같은지 대조한다."""
    actual = {str(item['certificate_id']): item for item in
              connection.execute('SELECT * FROM certificate_recommendation_contexts').fetchall()}
    for row in rows:
        saved = actual.get(row['certificate_id'])
        if saved is None or saved['qnet_code'] != row['qnet_code'] or saved['payload'] != row['payload'] or saved['content_sha256'] != row['content_sha256']:
            raise ValueError('저장한 추천 자료 조회 불일치')
    choices = {item['code']: item['payload'] for item in
               connection.execute('SELECT code,payload FROM recommendation_interest_categories').fetchall()}
    if any(choices.get(item['code']) != item for item in interests):
        raise ValueError('관심 선택지 조회 불일치')
    return {'verified_contexts': len(rows), 'verified_choices': len(interests),
            'reviewed_roles': sum(len(row['payload']['related_jobs']) for row in rows),
            'evidence_documents': sum(len(row['payload']['evidence_documents']) for row in rows)}


def run(apply: bool, rollback: bool = False) -> dict:
    """전체 자료를 검증한 뒤 한 트랜잭션으로 저장하고 별도 연결에서도 대조한다."""
    approved = json.loads((DATA / 'reviewed_recommendation_contexts.json').read_text(encoding='utf-8'))
    original = json.loads((DATA / 'candidate_contexts.json').read_text(encoding='utf-8'))
    interests = json.loads((DATA / 'interest_categories.json').read_text(encoding='utf-8'))
    rows, interests = prepare_recommendation_data(approved, original, interests)
    decisions = json.loads((DATA / 'step5_semantic_decisions.json').read_text(encoding='utf-8'))
    expected = [item for item in decisions if item['database_ready']]
    if approved != expected:
        raise ValueError('승인 목록과 의미 검토 결과 불일치')
    report = {'stage': 6, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'rollback_check' if rollback else 'apply' if apply else 'dry_run',
              'approved_contexts': len(rows), 'interest_choices': len(interests), 'github_pushed': False}
    with database_connection() as connection:
        connection.execute("SET LOCAL statement_timeout = '60s'")
        connection.execute("SET LOCAL lock_timeout = '5s'")
        validate_database_identities(connection, rows)
        before = get_existing_data_snapshot(connection)
        report['before_existing_data'] = before
        if apply:
            report['changes'] = upsert_recommendation_data(connection, rows, interests)
            report['verification'] = verify_database_results(connection, rows, interests)
            if get_existing_data_snapshot(connection) != before:
                raise ValueError('기존 데이터 변경을 발견해 저장을 취소합니다.')
        if rollback:
            connection.rollback()
    if apply and not rollback:
        with database_connection() as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            report['committed_verification'] = verify_database_results(connection, rows, interests)
            report['after_existing_data'] = get_existing_data_snapshot(connection)
        report['existing_data_unchanged'] = report['after_existing_data'] == before
        if not report['existing_data_unchanged']:
            raise ValueError('저장 후 기존 데이터가 달라져 추가 확인이 필요합니다.')
    report['database_changed'] = apply and not rollback and any(
        counts['inserted'] or counts['updated'] for counts in report.get('changes', {}).values())
    suffix = 'rollback' if rollback else 'apply' if apply else 'dry_run'
    (DATA / f'step6_database_{suffix}_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='승인 추천 자료 DB 저장')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.apply, args.rollback), ensure_ascii=True))
    except Exception as error:
        # 예외에 연결 정보가 포함될 수 있으므로 오류 클래스명만 표시한다.
        print(json.dumps({'failed': True, 'error_type': type(error).__name__}))
        raise SystemExit(1)

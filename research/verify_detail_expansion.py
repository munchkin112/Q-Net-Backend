"""확대한 상세정보 전체의 DB 구조와 대표 종목의 실제 HTTP 응답을 확인한다."""

from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.db.connection import database_connection
from backend.exam_schemas import ExamInformationInput
from backend.sync_batch import write_report


ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('subjects', 'pass_criteria', 'fees')


def verify() -> dict:
    """DB는 읽기만 하며, 종목별 검증 실패를 결과에 기록한다."""
    with database_connection() as connection:
        catalog = connection.execute('SELECT id, qnet_code, name, category FROM certificates ORDER BY qnet_code').fetchall()
        details = connection.execute('SELECT * FROM exam_information').fetchall()
        schedules = connection.execute('SELECT count(*) AS count FROM schedules').fetchone()['count']
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(), 'catalog_count': len(catalog),
        'detail_count': len(details), 'schedule_count': schedules,
        'data_status_counts': {}, 'phase_counts': {}, 'validation_errors': [], 'http_checks': [],
    }
    by_id = {row['id']: row for row in catalog}
    details_by_id = {row['certificate_id']: row for row in details}
    normalized = {}
    for row in details:
        cert = by_id[row['certificate_id']]
        try:
            information = ExamInformationInput(**{key: row[key] for key in
                ('certificate_id', 'subjects', 'pass_criteria', 'fees', 'raw_acquisition_text', 'raw_fee_text')})
            times = [getattr(information, field).retrieved_at for field in FIELDS if getattr(information, field).retrieved_at is not None]
            if row['retrieved_at'] != max(times):
                raise ValueError('전체 조회 시각과 필드별 원본 시각이 일치하지 않습니다.')
            status = 'complete' if all(getattr(information, field).status == 'available' for field in FIELDS) else 'partial'
            phases = '+'.join(information.subjects.phases)
            for key, value in (('data_status_counts', status), ('phase_counts', phases)):
                report[key][value] = report[key].get(value, 0) + 1
            normalized[row['certificate_id']] = information
        except ValueError as error:
            report['validation_errors'].append({'code': cert['qnet_code'], 'name': cert['name'], 'error': str(error)[:600]})

    # 기사·산업기사·기능사·기술사와 부분 수집·미수집 응답을 함께 검사한다.
    codes = ['1320', '1431', '1150', '2290', '7910', '6892', '0012', '0011', '0410', '1121', '6990', '7890']
    samples = [cert for cert in catalog if cert['qnet_code'] in codes]
    samples.extend(cert for cert in catalog if cert['category'] == 'T' and cert['id'] not in details_by_id)
    samples.append(next(cert for cert in catalog if cert['category'] == 'S'))
    selected = {cert['id']: cert for cert in samples}
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30) as client:
        for cert in selected.values():
            response = client.get('/api/v1/certificates/' + str(cert['id']))
            check = {'code': cert['qnet_code'], 'name': cert['name'], 'http_status': response.status_code, 'passed': False}
            if response.status_code == 200:
                payload = response.json()
                check['data_status'] = payload['data_status']
                check['certificate_id'] = payload['id']
                information = normalized.get(cert['id'])
                if information is not None:
                    expected = information.model_dump(mode='json')
                    check['passed'] = all(payload['exam_information'][field] == expected[field] for field in FIELDS)
                else:
                    check['passed'] = payload['data_status'] == 'unavailable' and payload['source_type'] == 'none'
            report['http_checks'].append(check)
    report['passed'] = not report['validation_errors'] and all(check['passed'] for check in report['http_checks'])
    return report


def main() -> None:
    """전체 검증 결과를 저장하고 실패가 있으면 종료 코드로 표시한다."""
    report = verify()
    write_report(ROOT / 'research/all_technical_detail_verification.json', report)
    print({key: report[key] for key in ('catalog_count', 'detail_count', 'data_status_counts', 'phase_counts', 'passed')})
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

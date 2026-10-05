"""전체 일정의 DB 구조와 실제 로컬 API 응답을 검증한다."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from backend.db.connection import database_connection
from backend.main import ScheduleResponse
from backend.sync_batch import PROJECT_ROOT, write_report


def main() -> None:
    """중복·기존 ID·확인된 날짜 보존과 대표 종목의 HTTP 조회를 확인한다."""
    before = json.loads((PROJECT_ROOT / 'research/schedules_before_expansion.json').read_text(encoding='utf-8'))
    with database_connection() as connection:
        rows = connection.execute('SELECT * FROM schedules ORDER BY certificate_id,round_key,phase').fetchall()
        catalog = connection.execute('SELECT id,qnet_code,name,category FROM certificates').fetchall()
        details_count = connection.execute('SELECT count(*) AS n FROM exam_information').fetchone()['n']
        duplicates = connection.execute('SELECT certificate_id,round_key,phase,count(*) FROM schedules GROUP BY certificate_id,round_key,phase HAVING count(*) > 1').fetchall()
    for row in rows:
        ScheduleResponse(**row)
    by_id = {str(row['id']): row for row in rows}
    fields = ('registration_start', 'registration_end', 'exam_start', 'exam_end', 'result_date',
              'result_display_end', 'vacancy_registration_start', 'vacancy_registration_end')
    for old in before['schedules']:
        assert old['id'] in by_id, '기존 일정 ID가 사라졌습니다.'
        current = by_id[old['id']]
        for field in fields:
            if old[field] is not None:
                assert str(current[field]) == old[field], '기존에 확인한 날짜가 달라졌습니다: ' + field
    assert not duplicates
    assert len(catalog) == before['counts']['certificates']
    assert details_count == before['counts']['exam_information']
    catalog_by_code = {row['qnet_code']: row for row in catalog}
    http_results = []
    codes = ['1320', '1431', '0012', '0011', '3021', '6032', '6990', '9777', '7030', '7910', '9771', '8070']
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=20) as client:
        for path in ('/health', '/health/database', '/docs', '/openapi.json'):
            response = client.get(path)
            assert response.status_code == 200, path
            http_results.append({'path': path, 'status_code': response.status_code})
        schema = client.get('/openapi.json').json()
        assert 'interview' in schema['components']['schemas']['ScheduleResponse']['properties']['phase']['enum']
        assert 'registration_periods' in schema['components']['schemas']['ScheduleResponse']['properties']
        for code in codes:
            certificate = catalog_by_code[code]
            path = f"/api/v1/certificates/{certificate['id']}/schedules?year=2026"
            response = client.get(path)
            assert response.status_code == 200, certificate['name']
            data = response.json()
            for row in data:
                ScheduleResponse(**row)
            expected = [row for row in rows if row['certificate_id'] == certificate['id'] and row['year'] == 2026]
            assert len(data) == len(expected), certificate['name']
            assert all('일반인' not in row['round_label'] and '회' in row['round_label'] for row in data)
            if code == '1320':
                third = next(row for row in data if row['phase'] == 'practical' and row['round_label'].endswith('3회'))
                assert [(p['starts_on'], p['ends_on']) for p in third['registration_periods']] == [('2026-09-21','2026-09-23'),('2026-09-28','2026-09-28')]
                assert all(p['source_url'] and p['retrieved_at'] for p in third['registration_periods'])
            if code == '0012':
                assert any(row['phase'] == 'interview' and len(row['registration_periods']) == 2 for row in data)
            if code == '6990':
                assert data and all(row['phase'] == 'practical' for row in data)
            if code == '9777':
                assert len(data) == 1 and data[0]['round_label'] == '2026년 수시 기사 1회'
            http_results.append({'qnet_code': code, 'name': certificate['name'], 'path': path,
                                 'status_code': response.status_code, 'schedule_rows': len(data)})
    result = {'verified_at': datetime.now(timezone.utc).isoformat(), 'certificate_count': len(catalog),
              'exam_information_count': details_count, 'schedule_count': len(rows),
              'scheduled_certificate_count': len({row['certificate_id'] for row in rows}),
              'phases': dict(Counter(row['phase'] for row in rows)), 'duplicate_keys': len(duplicates),
              'preserved_old_ids': len(before['schedules']), 'all_known_old_dates_preserved': True,
              'split_registration_rows': sum(len(row['registration_periods']) > 1 for row in rows),
              'vacancy_registration_rows': sum(row['vacancy_registration_start'] is not None for row in rows),
              'http_results': http_results, 'passed': True}
    write_report(PROJECT_ROOT / 'research/all_technical_schedule_verification.json', result)
    print(json.dumps({key: value for key, value in result.items() if key != 'http_results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

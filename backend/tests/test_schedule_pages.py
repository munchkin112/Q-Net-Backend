"""공식 일정의 표 예외·복수 접수기간·기존 정보 보존을 검증한다."""

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import unittest
from uuid import uuid4

from pydantic import ValidationError

from backend.official_schedule_page import cell_dates, normalize_schedule_page, registration_values
from backend.schemas import ScheduleInput


HEADER = '<tr><th>구분</th><th>필기원서접수</th><th>필기시험</th><th>필기합격 발표</th><th>실기원서접수</th><th>실기시험</th><th>최종합격자 발표일</th></tr>'


def normalize(rows, name='금형기술사'):
    """공식 표와 같은 구조를 사용해 날짜 해석을 확인한다."""
    return normalize_schedule_page({'id': uuid4(), 'name': name}, {
        'html': f'<h1>{name}</h1><table>{HEADER}{rows}</table>',
        'source_url': 'https://www.q-net.or.kr/crf005.do?jmCd=0012',
        'retrieved_at': datetime(2026, 10, 5, tzinfo=timezone.utc),
    })


def row(plan='2026년 정기 기술사 138회', omitted_close=False):
    """실제 기술사 원문과 같은 두 번의 면접 접수기간을 구성한다."""
    cells = [plan, '2026.01.06 ~ 2026.01.09', '2026.02.07', '2026.03.25',
             '2026.03.03 ~ 2026.03.06 / 2026.03.30 ~ 2026.04.02',
             '2026.05.02 ~ 2026.05.13', '2026.05.29']
    return '<tr>' + ''.join('<td>' + value + ('' if omitted_close and index == 4 else '</td>')
                           for index, value in enumerate(cells)) + '</tr>'


class SchedulePageTests(unittest.TestCase):
    def test_split_interview_registration_is_not_one_continuous_period(self):
        written, interview = normalize(row())
        self.assertEqual(written.phase, 'written')
        self.assertEqual(interview.phase, 'interview')
        self.assertEqual(len(interview.registration_periods), 2)
        self.assertEqual(interview.registration_periods[0].ends_on, date(2026, 3, 6))
        self.assertEqual(interview.registration_periods[1].starts_on, date(2026, 3, 30))

    def test_html_optional_cell_end_does_not_drop_registration(self):
        interview = normalize(row(omitted_close=True))[1]
        self.assertEqual(interview.registration_start, date(2026, 3, 3))
        self.assertEqual(interview.exam_start, date(2026, 5, 2))

    def test_restricted_school_row_is_excluded_without_losing_regular_rows(self):
        school = '<tr><td>2026년 정기 기능사</td><td colspan="3">특성화 고등학교 필기시험 면제자 검정 ※ 일반인 응시 불가</td><td>2026.05.11 ~ 2026.05.14<td>2026.06.13 ~ 2026.06.24</td><td>2026.07.10</td></tr>'
        result = normalize(row('2026년 정기 기능사 1회') + school, '컴퓨터응용밀링기능사')
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item.round_label.endswith('1회') for item in result))

    def test_vacancy_registration_is_separate(self):
        values = registration_values('2026.01.06 ~ 2026.01.09 [빈자리접수 : 2026.01.18 ~ 2026.01.19]')
        self.assertEqual(len(values['registration_periods']), 1)
        self.assertEqual(values['vacancy_registration_start'], date(2026, 1, 18))

    def test_explicit_empty_table_and_wrong_name_are_different(self):
        self.assertEqual(normalize('<tr><td colspan="7">시험 일정이 없습니다.</td></tr>'), [])
        with self.assertRaises(ValueError):
            normalize_schedule_page({'id': uuid4(), 'name': '다른종목'}, {'html': '<h1>금형기술사</h1>'})

    def test_wrong_columns_duplicate_rows_and_unknown_round_are_rejected(self):
        for rows in ('<tr><td>2026년 정기 기사 1회</td></tr>', row() + row(), row('확인 불가')):
            with self.assertRaises(ValueError):
                normalize(rows)

    def test_ad_hoc_exam_preserves_original_plan(self):
        result = normalize(row('2026년 수시 기사 1회'), '공공조달관리사')
        self.assertEqual(result[0].round_key, 'qnet-technical:2026년 수시 기사 1회')

    def test_truncated_or_invalid_date_is_not_guessed(self):
        for value in ('2026.03.01 ~ 03.03', '2026.02.30', '2026년 3월 1일'):
            with self.assertRaises(ValueError):
                cell_dates(value, {0, 1, 2})

    def test_period_overlap_and_wrong_envelope_are_rejected(self):
        schedule = normalize(row())[1].model_dump(mode='json')
        for periods in ([{'starts_on': '2026-03-03', 'ends_on': '2026-04-01'}, {'starts_on': '2026-03-30', 'ends_on': '2026-04-02'}],
                        [{'starts_on': '2026-03-04', 'ends_on': '2026-04-02'}]):
            with self.assertRaises(ValidationError):
                ScheduleInput(**{**schedule, 'registration_periods': periods})

    def test_annual_notice_splits_article_registration_with_its_own_source(self):
        rows = row('2026년 정기 기사 3회').replace(
            '2026.03.03 ~ 2026.03.06 / 2026.03.30 ~ 2026.04.02', '2026.09.21 ~ 2026.09.28'
        ).replace('2026.05.02 ~ 2026.05.13', '2026.10.24 ~ 2026.11.13').replace('2026.05.29', '2026.12.18')
        notice = {'source_url': 'https://example.com/official-notice.pdf', 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'registration_overrides': [{'round_label': '2026년 정기 기사 3회', 'phase': 'practical',
                    'periods': [{'starts_on': '2026-09-21', 'ends_on': '2026-09-23'}, {'starts_on': '2026-09-28', 'ends_on': '2026-09-28'}]}]}
        response = {'html': '<h1>정보처리기사</h1><table>' + HEADER + rows + '</table>',
                    'source_url': 'https://www.q-net.or.kr/crf005.do?jmCd=1320', 'retrieved_at': datetime.now(timezone.utc)}
        result = normalize_schedule_page({'id': uuid4(), 'name': '정보처리기사'}, response, notice)[1]
        self.assertEqual(result.registration_periods[0].ends_on, date(2026, 9, 23))
        self.assertEqual(result.registration_periods[1].starts_on, date(2026, 9, 28))
        self.assertEqual(result.registration_periods[0].source_url, notice['source_url'])
        notice['registration_overrides'][0]['periods'][0]['starts_on'] = '2026-09-22'
        with self.assertRaises(ValueError):
            normalize_schedule_page({'id': uuid4(), 'name': '정보처리기사'}, response, notice)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), '테스트 PostgreSQL 연결 정보 미제공')
class ScheduleMigrationTests(unittest.TestCase):
    def test_migration_preserves_ids_and_save_does_not_erase_known_dates(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from backend.db.repository import save_schedule
        from backend.tests.test_database_inputs import sample_schedule

        connection = psycopg.connect(os.environ['TEST_DATABASE_URL'], row_factory=dict_row, connect_timeout=10)
        try:
            schema = 'test_schedule_' + uuid4().hex
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            directory = Path(__file__).parents[1] / 'db'
            connection.execute((directory / 'schema.sql').read_text(encoding='utf-8'))
            certificate_id = uuid4()
            connection.execute("INSERT INTO certificates(id, qnet_code, name, category, source_url, last_synced_at) VALUES (%s, '0012', '금형기술사', 'T', 'https://www.q-net.or.kr/', now())", (certificate_id,))
            first = sample_schedule(certificate_id=certificate_id, result_display_end=date(2026, 12, 31))
            saved = save_schedule(connection, first)
            connection.execute('ALTER TABLE schedules DROP COLUMN registration_periods')
            migration = (directory / 'schedule_periods.sql').read_text(encoding='utf-8')
            connection.execute(migration)
            connection.execute(migration)
            migrated = connection.execute('SELECT * FROM schedules').fetchone()
            self.assertEqual(migrated['id'], saved['id'])
            self.assertEqual(migrated['registration_periods'], [{'starts_on': '2026-09-21', 'ends_on': '2026-09-28'}])
            newer = first.model_copy(update={'result_display_end': None, 'last_synced_at': first.last_synced_at + timedelta(days=1)})
            retained = save_schedule(connection, newer, preserve_known=True)
            self.assertEqual(retained['result_display_end'], date(2026, 12, 31))
            self.assertEqual(retained['last_synced_at'], first.last_synced_at)
            newer = ScheduleInput(**{**newer.model_dump(), 'registration_periods': [
                {'starts_on': '2026-09-21', 'ends_on': '2026-09-23', 'source_url': 'https://www.q-net.or.kr/', 'retrieved_at': newer.last_synced_at},
                {'starts_on': '2026-09-28', 'ends_on': '2026-09-28', 'source_url': 'https://www.q-net.or.kr/', 'retrieved_at': newer.last_synced_at},
            ]})
            enriched = save_schedule(connection, newer, preserve_known=True)
            self.assertEqual(len(enriched['registration_periods']), 2)
            self.assertEqual(enriched['source_url'], saved['source_url'])
            self.assertEqual(enriched['last_synced_at'], saved['last_synced_at'])
            self.assertEqual(enriched['result_display_end'], date(2026, 12, 31))
            old_periods = ScheduleInput(**{**newer.model_dump(), 'last_synced_at': newer.last_synced_at + timedelta(days=1),
                'registration_periods': [{'starts_on': '2026-09-21', 'ends_on': '2026-09-28',
                    'source_url': 'https://www.q-net.or.kr/', 'retrieved_at': first.last_synced_at}]})
            self.assertEqual(len(save_schedule(connection, old_periods, preserve_known=True)['registration_periods']), 2)
            interview = normalize(row())[1].model_copy(update={'certificate_id': certificate_id})
            inserted = save_schedule(connection, interview)
            self.assertEqual(len(inserted['registration_periods']), 2)
            self.assertEqual(inserted['phase'], 'interview')
            # 같은 종목 저장 중 오류가 나면 앞선 단계도 확정하지 않는다.
            count = connection.execute('SELECT count(*) AS n FROM schedules').fetchone()['n']
            with self.assertRaises(RuntimeError):
                with connection.transaction():
                    save_schedule(connection, interview.model_copy(update={'round_key': 'rollback-example'}))
                    raise RuntimeError('검증용 취소')
            self.assertEqual(connection.execute('SELECT count(*) AS n FROM schedules').fetchone()['n'], count)
        finally:
            connection.rollback()
            connection.close()

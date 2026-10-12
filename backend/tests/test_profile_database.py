"""공용 테이블 대신 연결별 임시 테이블과 롤백으로 실제 SQL 저장을 시험한다."""
import os
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.db.connection import database_connection
from backend.db.profile_repository import get_profile_form, update_profile_form, ProfileVersionConflict
from backend.profile_service import build_profile_response
from backend.profile_router import create_profile_router
from backend.recommendation_router import create_recommendation_router


@unittest.skipUnless(os.environ.get('QNET_PROFILE_DB_TEST') == '1', '명시적인 임시 DB 시험 옵션이 필요합니다.')
class ProfileDatabaseTests(unittest.TestCase):
    def test_initial_partial_clear_conflict_ownership_and_rollback(self):
        first, second = uuid4(), uuid4()
        form = {'interest_category_codes': ['20'], 'education_level': 'university',
                'education_status': 'graduated', 'major': '컴퓨터공학',
                'has_career': True, 'career_years': 2.5}
        with database_connection() as connection:
            before = connection.execute("SELECT count(*) AS count FROM public.user_profiles").fetchone()['count']
            with connection.transaction(force_rollback=True):
                connection.execute('CREATE TEMP TABLE users(id uuid PRIMARY KEY) ON COMMIT DROP')
                # 임시 테이블의 외래키는 임시 테이블만 참조할 수 있어 선택지도 격리한다.
                connection.execute('CREATE TEMP TABLE recommendation_interest_categories(code text PRIMARY KEY) ON COMMIT DROP')
                connection.execute("INSERT INTO recommendation_interest_categories VALUES ('20')")
                connection.execute('''CREATE TEMP TABLE user_profiles(
                    user_id uuid PRIMARY KEY REFERENCES users(id),education_level text,education_status text,
                    major text,major_status text,has_career boolean,career_history jsonb NOT NULL DEFAULT '[]',
                    qualifications jsonb NOT NULL DEFAULT '[]',updated_at timestamptz NOT NULL DEFAULT now()) ON COMMIT DROP''')
                schema = (Path(__file__).parents[1] / 'db/profile_form.sql').read_text(encoding='utf-8')
                connection.execute(schema)
                connection.execute(schema)  # 재적용해도 새 열을 중복 생성하지 않는다.
                connection.execute('INSERT INTO users VALUES (%s),(%s)', (first, second))
                self.assertFalse(build_profile_response(get_profile_form(connection, first))['profile_completed'])
                initial = build_profile_response(update_profile_form(connection, first, 0, form))
                self.assertEqual(initial['profile_version'], 1)
                self.assertEqual(initial['profile']['career_years'], 2.5)
                self.assertIsNone(get_profile_form(connection, second))
                modified = build_profile_response(update_profile_form(connection, first, 1,
                                                   {'major': None, 'has_career': False}))
                self.assertEqual(modified['profile_version'], 2)
                self.assertIsNone(modified['profile']['major'])
                self.assertIsNone(modified['profile']['career_years'])
                self.assertEqual(modified['profile']['interest_category_codes'], ['20'])
                with self.assertRaises(ProfileVersionConflict):
                    update_profile_form(connection, first, 1, {'major': '덮어쓰기'})
                with self.assertRaises(ValueError):
                    update_profile_form(connection, first, 2, {'has_career': True})
                unchanged = build_profile_response(update_profile_form(connection, first, 2, {}))
                self.assertEqual(unchanged, modified)
                app = FastAPI()
                verified_user = lambda: SimpleNamespace(id=first, email=None)
                agent = Mock(return_value={'selection': {'status': 'no_results', 'items': []}, 'candidates': []})
                app.include_router(create_profile_router(verified_user))
                app.include_router(create_recommendation_router(verified_user, run_agent=agent))
                with patch('backend.profile_service.database_connection', side_effect=lambda: nullcontext(connection)):
                    client = TestClient(app)
                    response = client.patch('/me/profile', json={'profile_version': 2, 'major': '수정 전공'})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['profile_version'], 3)
                    self.assertEqual(client.get('/me/profile').json()['profile']['major'], '수정 전공')
                    self.assertEqual(client.post('/recommendations', json={}).status_code, 200)
                    self.assertEqual(agent.call_args.args[0]['major'], '수정 전공')
                    self.assertEqual(agent.call_args.args[1], ['20'])
            after = connection.execute("SELECT count(*) AS count FROM public.user_profiles").fetchone()['count']
            self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()

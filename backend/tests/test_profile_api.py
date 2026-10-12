"""미등록 라우터에서 인증 사용자·부분 수정·저장 검증 계약을 시험한다."""
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.profile_router import create_profile_router
from backend.profile_service import merge_profile_form
from backend.profile_service import build_profile_response
from backend.db.profile_repository import update_profile_form, ProfileVersionConflict

USER = UUID('11111111-1111-4111-8111-111111111111')
FORM = {'interest_category_codes': ['20'], 'education_level': 'university',
        'education_status': 'graduated', 'major': None, 'has_career': False, 'career_years': None}


class ProfileApiTests(unittest.TestCase):
    def client(self, configured=True):
        self.read = Mock(return_value={'profile': FORM, 'profile_completed': True,
                                      'missing_fields': [], 'profile_version': 2})
        self.save = Mock(return_value=self.read.return_value)
        app = FastAPI()
        if configured:
            router = create_profile_router(lambda: SimpleNamespace(id=USER, email=None),
                                           self.read, self.save, lambda: [{'code': '20', 'name': '정보통신'}])
        else:
            router = create_profile_router()
        app.include_router(router)
        return TestClient(app)

    def test_auth_model_id_used_and_client_user_id_rejected(self):
        client = self.client()
        self.assertEqual(client.get('/me/profile').status_code, 200)
        self.read.assert_called_once_with(USER)
        self.assertEqual(client.patch('/me/profile', json={'profile_version': 2, 'user_id': str(USER)}).status_code, 422)
        self.save.assert_not_called()

    def test_partial_patch_requires_version_and_keeps_other_fields(self):
        client = self.client()
        self.assertEqual(client.patch('/me/profile', json={'major': '컴퓨터공학'}).status_code, 422)
        response = client.patch('/me/profile', json={'profile_version': 2, 'major': '컴퓨터공학'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.save.call_args.args[:2], (USER, 2))
        self.assertEqual(self.save.call_args.args[2], {'major': '컴퓨터공학'})

    def test_major_clear_and_career_change(self):
        merged = merge_profile_form({**FORM, 'major': '기계', 'has_career': True, 'career_years': 3},
                                    {'major': None, 'has_career': False})
        self.assertIsNone(merged['major'])
        self.assertIsNone(merged['career_years'])
        self.assertEqual(merged['education_level'], 'university')
        with self.assertRaises(ValueError):
            merge_profile_form(FORM, {'has_career': True})
        with self.assertRaises(ValueError):
            merge_profile_form(FORM, {'interest_category_codes': ['20', '19']})

    def test_stale_version_is_409_and_db_error_not_leaked(self):
        client = self.client()
        self.save.side_effect = ProfileVersionConflict()
        self.assertEqual(client.patch('/me/profile', json={'profile_version': 1}).status_code, 409)
        self.read.side_effect = RuntimeError('private-password')
        response = client.get('/me/profile')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-password', response.text)

    def test_unconfigured_auth_is_fail_closed(self):
        client = self.client(configured=False)
        self.assertEqual(client.get('/me/profile').status_code, 401)
        with patch('backend.auth_dependencies.get_auth_token_settings',
                   side_effect=RuntimeError('auth settings are unavailable')):
            response = client.get('/interest-categories',
                                  headers={'Authorization': 'Bearer fake'})
        self.assertEqual(response.status_code, 503)

    def test_invalid_profile_never_written(self):
        connection = Mock()
        connection.transaction.return_value = nullcontext()
        connection.execute.side_effect = [Mock(fetchone=Mock(return_value={'id': USER})),
                                          Mock(fetchone=Mock(return_value=None))]
        with self.assertRaises(ValueError):
            update_profile_form(connection, USER, 0, {'education_level': 'university'})
        self.assertEqual(connection.execute.call_count, 2)
        self.assertNotIn('INSERT', connection.execute.call_args.args[0])

    def test_unentered_and_legacy_profile_needs_input(self):
        response = build_profile_response(None)
        self.assertIsNone(response['profile'])
        self.assertFalse(response['profile_completed'])
        row = {'interest_category_code': None, 'education_level': '대졸 / 재학',
               'education_status': None, 'major': None, 'has_career': False,
               'career_years': None, 'profile_version': 0}
        response = build_profile_response(row)
        self.assertIn('interest_category_codes', response['missing_fields'])
        self.assertIn('education_level', response['missing_fields'])


if __name__ == '__main__':
    unittest.main()

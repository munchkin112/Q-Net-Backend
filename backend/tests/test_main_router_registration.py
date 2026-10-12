"""실제 FastAPI 앱에서 보호 라우터가 인증과 함께 등록되는지 확인한다."""
from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from backend.auth_dependencies import get_current_user
from backend.auth_schemas import AuthUserResponse
from backend.main import app


class MainRouterRegistrationTests(unittest.TestCase):
    def test_profile_and_recommendation_routes_require_authentication(self):
        client = TestClient(app)
        checks = [
            ('GET', '/interest-categories'),
            ('GET', '/me/profile'),
            ('POST', '/recommendations'),
            ('GET', '/certificates/79a6a7a3-5fbc-4b64-80dd-732206f3fb81/career-info'),
        ]

        for method, path in checks:
            with self.subTest(method=method, path=path):
                if method == 'GET':
                    response = client.get(path)
                else:
                    response = client.post(path, json={})
                self.assertEqual(response.status_code, 401)

    def test_authenticated_profile_route_accepts_auth_user_model(self):
        user_id = UUID('11111111-1111-4111-8111-111111111111')
        app.dependency_overrides[get_current_user] = lambda: AuthUserResponse(id=user_id, email='test@example.com')
        try:
            with patch('backend.profile_service.database_connection', return_value=nullcontext(None)), \
                    patch('backend.profile_service.get_profile_form', return_value=None):
                response = TestClient(app).get('/me/profile')
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['profile'])
        self.assertFalse(response.json()['profile_completed'])

    def test_authenticated_recommendation_route_reads_profile_with_user_uuid(self):
        user_id = UUID('11111111-1111-4111-8111-111111111111')
        app.dependency_overrides[get_current_user] = lambda: AuthUserResponse(id=user_id, email='test@example.com')
        read_profile = Mock(return_value=None)
        try:
            with patch('backend.profile_service.database_connection', return_value=nullcontext(None)), \
                    patch('backend.profile_service.get_profile_form', read_profile):
                response = TestClient(app).post('/recommendations', json={})
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['code'], 'PROFILE_INCOMPLETE')
        read_profile.assert_called_once_with(None, user_id)


if __name__ == '__main__':
    unittest.main()

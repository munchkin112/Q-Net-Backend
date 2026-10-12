"""Bearer 보호, 토큰 갱신, 로그아웃의 API 계약을 외부 서비스 없이 검증한다."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from backend.auth_dependencies import (
    AuthRequestError,
    get_current_user,
    handle_auth_request_error,
)
from backend.auth_logout_service import handle_auth_logout
from backend.auth_refresh import create_refresh_token
from backend.auth_refresh_service import AuthRefreshResult, RefreshTokenReuseError
from backend.auth_router import AUTH_REFRESH_COOKIE_NAME, auth_router, set_auth_refresh_cookie
from backend.auth_schemas import AuthUserResponse, TokenRefreshResponse
from backend.auth_tokens import create_access_token


TEST_SECRET = "test-only-auth-signing-key-32-characters-long"
TEST_ORIGIN = "https://frontend.example"


class AuthContractTests(unittest.TestCase):
    def test_refresh_cookie_for_unbounded_session_expires_after_30_days(self):
        response = Response()
        set_auth_refresh_cookie(response, 'opaque-refresh-token', None, cookie_secure=True)
        self.assertIn('Max-Age=2592000', response.headers['set-cookie'])
        self.assertIn('HttpOnly', response.headers['set-cookie'])

    def test_bearer_checks_database_session_and_rejects_revoked_session(self):
        """같은 유효한 액세스 토큰도 DB 세션을 폐기하면 즉시 차단된다."""
        app = FastAPI()
        app.add_exception_handler(AuthRequestError, handle_auth_request_error)

        @app.get("/protected")
        def get_protected(user: AuthUserResponse = Depends(get_current_user)) -> AuthUserResponse:
            return user

        user_id = uuid4()
        session_id = uuid4()
        access_token = create_access_token(user_id, session_id, secret_key=TEST_SECRET)
        session = {
            "id": session_id,
            "user_id": user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "revoked_at": None,
        }
        settings = {"AUTH_ACCESS_TOKEN_SECRET": TEST_SECRET}

        with patch.dict(os.environ, settings):
            with patch(
                "backend.auth_user_service.database_connection",
                return_value=nullcontext(object()),
            ):
                with patch("backend.auth_user_service.get_auth_session", return_value=session):
                    with patch(
                        "backend.auth_user_service.get_user",
                        return_value={"id": user_id, "email": "user@example.com"},
                    ):
                        with TestClient(app) as client:
                            missing = client.get("/protected")
                            active = client.get(
                                "/protected",
                                headers={"Authorization": f"Bearer {access_token}"},
                            )
                            session["revoked_at"] = datetime.now(timezone.utc)
                            revoked = client.get(
                                "/protected",
                                headers={"Authorization": f"Bearer {access_token}"},
                            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["error"]["code"], "AUTHENTICATION_REQUIRED")
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["id"], str(user_id))
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(revoked.json()["error"]["code"], "SESSION_INVALID")

    def test_refresh_endpoint_returns_access_token_and_rotates_cookie(self):
        """새 액세스 토큰은 JSON에, 새 리프레시 토큰은 HttpOnly 쿠키에만 담긴다."""
        app = FastAPI()
        app.include_router(auth_router)
        old_refresh_token = create_refresh_token()
        new_refresh_token = create_refresh_token()
        result = AuthRefreshResult(
            response=TokenRefreshResponse(access_token="new-access-token", expires_in=1800),
            refresh_token=new_refresh_token,
            session_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        settings = {
            "AUTH_ACCESS_TOKEN_SECRET": TEST_SECRET,
            "AUTH_ALLOWED_ORIGINS": TEST_ORIGIN,
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, settings):
            with patch("backend.auth_router.update_auth_tokens", return_value=result) as update:
                with TestClient(app, base_url="https://testserver") as client:
                    response = client.post(
                        "/auth/refresh",
                        headers={
                            "Origin": TEST_ORIGIN,
                            "Cookie": f"{AUTH_REFRESH_COOKIE_NAME}={old_refresh_token}",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["access_token"], "new-access-token")
        self.assertNotIn(new_refresh_token, response.text)
        self.assertIn(new_refresh_token, response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        update.assert_called_once_with(old_refresh_token, secret_key=TEST_SECRET)

    def test_refresh_reuse_clears_cookie_and_wrong_origin_never_rotates(self):
        """재사용된 토큰은 재로그인을 요구하고, 허용되지 않은 출처는 먼저 차단한다."""
        app = FastAPI()
        app.include_router(auth_router)
        settings = {
            "AUTH_ACCESS_TOKEN_SECRET": TEST_SECRET,
            "AUTH_ALLOWED_ORIGINS": TEST_ORIGIN,
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, settings):
            with patch(
                "backend.auth_router.update_auth_tokens",
                side_effect=RefreshTokenReuseError("reused"),
            ) as update:
                with TestClient(app, base_url="https://testserver") as client:
                    rejected_origin = client.post(
                        "/auth/refresh",
                        headers={"Origin": "https://attacker.example"},
                    )
                    reused = client.post(
                        "/auth/refresh",
                        headers={
                            "Origin": TEST_ORIGIN,
                            "Cookie": f"{AUTH_REFRESH_COOKIE_NAME}={create_refresh_token()}",
                        },
                    )

        self.assertEqual(rejected_origin.status_code, 403)
        self.assertEqual(rejected_origin.json()["error"]["code"], "AUTH_ORIGIN_FORBIDDEN")
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(reused.json()["error"]["code"], "REFRESH_TOKEN_INVALID")
        self.assertIn("Max-Age=0", reused.headers["set-cookie"])
        update.assert_called_once()

    def test_logout_service_revokes_matching_session(self):
        """로그아웃은 전달받은 리프레시 토큰의 사용자 세션만 폐기한다."""
        token = create_refresh_token()
        session_id = uuid4()
        user_id = uuid4()
        connection = object()
        record = {"session_id": session_id, "user_id": user_id, "revoked_at": None}

        with patch(
            "backend.auth_logout_service.database_connection",
            return_value=nullcontext(connection),
        ):
            with patch(
                "backend.auth_logout_service.get_auth_refresh_token",
                return_value=record,
            ):
                with patch(
                    "backend.auth_logout_service.update_auth_session_revocation",
                    return_value=True,
                ) as revoke:
                    handle_auth_logout(token)

        revoke.assert_called_once_with(connection, session_id, user_id)


if __name__ == "__main__":
    unittest.main()

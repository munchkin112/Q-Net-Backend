"""Google 로그인 시작과 서비스 세션의 중요한 연결을 외부 호출 없이 검증한다."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from backend.auth_google import GoogleTokenResponse, fetch_google_tokens
from backend.auth_identity import GoogleIdentity
from backend.auth_login_service import GoogleLoginSessionResult, create_google_login_session
from backend.auth_refresh import create_refresh_token
from backend.auth_refresh_service import RefreshTokenReuseError, update_auth_tokens
from backend.auth_router import (
    AUTH_REFRESH_COOKIE_NAME,
    GOOGLE_OAUTH_COOKIE_NAME,
    auth_router,
)
from backend.auth_state import validate_google_oauth_state
from backend.auth_schemas import AuthUserResponse
from backend.auth_tokens import validate_access_token


TEST_SECRET = "test-only-auth-signing-key-32-characters-long"


class GoogleAuthenticationTests(unittest.TestCase):
    def test_login_start_binds_state_to_browser_and_rejects_reuse(self):
        """로그인 요청의 state는 해당 브라우저에서 한 번만 사용할 수 있다."""
        app = FastAPI()
        app.include_router(auth_router)
        google_settings = {
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "https://frontend.example/callback",
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, google_settings):
            with TestClient(app, base_url="https://testserver") as client:
                response = client.get("/auth/google/authorize")
                browser_token = client.cookies.get(GOOGLE_OAUTH_COOKIE_NAME)

        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIsNotNone(browser_token)

        query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
        state = query["state"][0]
        self.assertIn("https://www.googleapis.com/auth/calendar.events.owned", query["scope"][0])

        with self.assertRaises(ValueError):
            validate_google_oauth_state(state, "another-browser-token")
        validate_google_oauth_state(state, browser_token)
        with self.assertRaises(ValueError):
            validate_google_oauth_state(state, browser_token)

    def test_google_code_exchange_keeps_calendar_token_on_server(self):
        """Google의 토큰 응답에서 Calendar 갱신 토큰과 권한을 받는다."""
        def respond_to_google(request: httpx.Request) -> httpx.Response:
            self.assertEqual(str(request.url), "https://oauth2.googleapis.com/token")
            self.assertEqual(parse_qs(request.content.decode())["code"], ["test-code"])
            return httpx.Response(200, json={
                "access_token": "google-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": "google-id-token",
                "refresh_token": "google-calendar-refresh-token",
                "scope": "openid email https://www.googleapis.com/auth/calendar.events.owned",
            })

        google_settings = {
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "https://frontend.example/callback",
        }
        with patch.dict(os.environ, google_settings):
            tokens = fetch_google_tokens(
                "test-code",
                transport=httpx.MockTransport(respond_to_google),
            )

        self.assertEqual(tokens.refresh_token, "google-calendar-refresh-token")
        self.assertIn("calendar.events.owned", tokens.scope)

    def test_login_callback_connects_google_calendar_and_service_cookie(self):
        """검증된 Google 응답만 로그인 세션 저장 함수로 전달한다."""
        app = FastAPI()
        app.include_router(auth_router)
        user_id = uuid4()
        calendar_writer = Mock(return_value=True)
        google_tokens = GoogleTokenResponse(
            access_token="google-access-token",
            token_type="Bearer",
            expires_in=3600,
            id_token="google-id-token",
            refresh_token="google-calendar-refresh-token",
            scope="openid email https://www.googleapis.com/auth/calendar.events.owned",
        )
        identity = GoogleIdentity(
            provider_subject_id="test-google-sub",
            email="user@example.com",
        )
        login_result = GoogleLoginSessionResult(
            user=AuthUserResponse(id=user_id, email=identity.email),
            access_token="service-access-token",
            refresh_token=create_refresh_token(),
            expires_in=1800,
            session_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            calendar_connected=True,
        )
        settings = {
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "https://frontend.example/callback",
            "AUTH_ACCESS_TOKEN_SECRET": TEST_SECRET,
            "AUTH_ALLOWED_ORIGINS": "https://frontend.example",
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, settings):
            with patch("backend.auth_router.get_calendar_credential_creator", return_value=calendar_writer):
                with patch("backend.auth_router.fetch_google_tokens", return_value=google_tokens) as exchange:
                    with patch("backend.auth_router.validate_google_id_token", return_value=identity) as verify:
                        with patch("backend.auth_router.create_google_login_session", return_value=login_result) as save:
                            with TestClient(app, base_url="https://testserver") as client:
                                start = client.get("/auth/google/authorize")
                                state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
                                response = client.post(
                                    "/auth/google",
                                    headers={"Origin": "https://frontend.example"},
                                    json={"code": "test-code", "state": state},
                                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], str(user_id))
        self.assertTrue(response.json()["calendar_connected"])
        self.assertEqual(response.json()["access_token"], "service-access-token")
        self.assertNotIn("google-calendar-refresh-token", response.text)
        self.assertNotIn(login_result.refresh_token, response.text)
        self.assertTrue(any(
            AUTH_REFRESH_COOKIE_NAME in cookie and "HttpOnly" in cookie
            for cookie in response.headers.get_list("set-cookie")
        ))
        self.assertTrue(any(
            GOOGLE_OAUTH_COOKIE_NAME in cookie and "Max-Age=0" in cookie
            for cookie in response.headers.get_list("set-cookie")
        ))
        exchange.assert_called_once_with("test-code")
        verify.assert_called_once_with("google-id-token")
        save.assert_called_once_with(
            identity,
            secret_key=TEST_SECRET,
            google_refresh_token="google-calendar-refresh-token",
            google_scopes=google_tokens.scope,
            calendar_credential_creator=calendar_writer,
        )

    def test_login_callback_rejects_unmatched_state_before_token_exchange(self):
        """브라우저 쿠키와 맞지 않는 state로는 Google 코드를 교환하지 않는다."""
        app = FastAPI()
        app.include_router(auth_router)
        settings = {
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "https://frontend.example/callback",
            "AUTH_ACCESS_TOKEN_SECRET": TEST_SECRET,
            "AUTH_ALLOWED_ORIGINS": "https://frontend.example",
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, settings):
            with patch("backend.auth_router.get_calendar_credential_creator", return_value=Mock()):
                with patch("backend.auth_router.fetch_google_tokens") as exchange:
                    with TestClient(app, base_url="https://testserver") as client:
                        response = client.post(
                            "/auth/google",
                            headers={"Origin": "https://frontend.example"},
                            json={"code": "test-code", "state": "unmatched-state"},
                        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "GOOGLE_STATE_INVALID")
        exchange.assert_not_called()

    def test_login_callback_reports_missing_calendar_storage(self):
        """Calendar 저장 기능이 없으면 Google 코드를 소비하지 않고 중단한다."""
        app = FastAPI()
        app.include_router(auth_router)
        settings = {
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "https://frontend.example/callback",
            "AUTH_ACCESS_TOKEN_SECRET": TEST_SECRET,
            "AUTH_ALLOWED_ORIGINS": "https://frontend.example",
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, settings):
            with patch("backend.auth_router.get_calendar_credential_creator", side_effect=RuntimeError):
                with patch("backend.auth_router.fetch_google_tokens") as exchange:
                    with TestClient(app, base_url="https://testserver") as client:
                        response = client.post(
                            "/auth/google",
                            headers={"Origin": "https://frontend.example"},
                            json={"code": "test-code", "state": "test-state"},
                        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AUTH_SERVICE_UNAVAILABLE")
        exchange.assert_not_called()

    def test_login_session_passes_calendar_credentials_in_same_transaction(self):
        """로그인 세션과 Calendar 저장 함수가 동일한 DB 연결을 사용한다."""
        connection = object()
        user_id = uuid4()
        session_id = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        calendar_writer = Mock(return_value=True)
        identity = GoogleIdentity(
            provider_subject_id="test-google-sub",
            email="user@example.com",
        )

        with patch("backend.auth_login_service.database_connection", return_value=nullcontext(connection)):
            with patch("backend.auth_login_service.create_user", return_value={"id": user_id, "email": identity.email}):
                with patch("backend.auth_login_service.create_auth_session", return_value={
                    "id": session_id, "user_id": user_id, "expires_at": expires_at,
                }):
                    with patch("backend.auth_login_service.create_auth_refresh_token"):
                        result = create_google_login_session(
                            identity,
                            secret_key=TEST_SECRET,
                            google_refresh_token="google-calendar-refresh-token",
                            google_scopes="openid email calendar.events.owned",
                            calendar_credential_creator=calendar_writer,
                        )

        calendar_writer.assert_called_once_with(
            connection,
            user_id,
            "google-calendar-refresh-token",
            "openid email calendar.events.owned",
        )
        claims = validate_access_token(result.access_token, secret_key=TEST_SECRET)
        self.assertEqual(claims.user_id, user_id)
        self.assertEqual(claims.session_id, session_id)
        self.assertTrue(result.calendar_connected)

    def test_reused_refresh_token_revokes_session(self):
        """이미 사용한 리프레시 토큰이 다시 오면 세션을 폐기한다."""
        refresh_token = create_refresh_token()
        session_id = uuid4()
        user_id = uuid4()
        token_record = {
            "session_id": session_id,
            "user_id": user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            "revoked_at": None,
            "used_at": datetime.now(timezone.utc),
        }
        connection = object()

        with patch("backend.auth_refresh_service.database_connection", return_value=nullcontext(connection)):
            with patch("backend.auth_refresh_service.get_auth_refresh_token", return_value=token_record):
                with patch("backend.auth_refresh_service.update_auth_session_revocation", return_value=True) as revoke:
                    with patch("backend.auth_refresh_service.create_auth_refresh_token") as create_new_token:
                        with self.assertRaises(RefreshTokenReuseError):
                            update_auth_tokens(refresh_token, secret_key=TEST_SECRET)

        revoke.assert_called_once_with(connection, session_id, user_id)
        create_new_token.assert_not_called()

    def test_logout_endpoint_deletes_refresh_cookie(self):
        """로그아웃은 저장된 세션 종료를 호출하고 브라우저 쿠키를 지운다."""
        app = FastAPI()
        app.include_router(auth_router)
        headers = {
            "Origin": "https://frontend.example",
            "Cookie": f"{AUTH_REFRESH_COOKIE_NAME}=test-refresh-token",
        }
        settings = {
            "AUTH_ALLOWED_ORIGINS": "https://frontend.example",
            "AUTH_COOKIE_SECURE": "true",
        }

        with patch.dict(os.environ, settings):
            with patch("backend.auth_router.handle_auth_logout") as logout:
                with TestClient(app, base_url="https://testserver") as client:
                    response = client.post("/auth/logout", headers=headers)

        self.assertEqual(response.status_code, 204)
        logout.assert_called_once_with("test-refresh-token")
        self.assertIn(f"{AUTH_REFRESH_COOKIE_NAME}=", response.headers["set-cookie"])
        self.assertIn("Max-Age=0", response.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()

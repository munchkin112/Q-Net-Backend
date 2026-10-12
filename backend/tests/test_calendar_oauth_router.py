"""Calendar 전용 OAuth가 앱 로그인 토큰을 발급하지 않는지 검증한다."""

import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.calendar_oauth_router import create_calendar_oauth_router
from backend.calendar_oauth_service import CalendarGoogleTokenResponse
from backend.calendar_service import GOOGLE_CALENDAR_SCOPE


class CalendarOAuthRouterTests(unittest.TestCase):
    def client(self, exchange=None, save=None):
        app = FastAPI()
        self.exchange = exchange or Mock(return_value=CalendarGoogleTokenResponse(
            access_token="google-access",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="google-refresh",
            scope=GOOGLE_CALENDAR_SCOPE,
        ))
        self.save = save or Mock(return_value="opaque-calendar-session")
        app.include_router(create_calendar_oauth_router(
            make_authorization_url=lambda state: f"https://google.test/auth?state={state}",
            exchange_code=self.exchange,
            save_connection=self.save,
            read_allowed_origins=lambda: {"http://localhost:5173"},
            read_cookie_secure=lambda: False,
        ))
        return TestClient(app)

    def test_authorization_sets_state_cookie_and_callback_sets_calendar_cookie_only(self):
        client = self.client()
        start = client.get("/calendar/google/authorize")
        state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

        self.assertIn("qnet_calendar_oauth", start.cookies)
        response = client.post(
            "/calendar/google/callback",
            headers={"Origin": "http://localhost:5173"},
            json={"code": "one-time-code", "state": state},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["calendar_connected"])
        self.assertNotIn("access_token", response.json())
        self.assertIn("qnet_calendar_session", response.cookies)
        self.assertEqual(self.save.call_args.args, ("google-refresh", GOOGLE_CALENDAR_SCOPE))
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("path=/calendar", cookie)

    def test_callback_rejects_unapproved_origin_and_missing_refresh_token(self):
        client = self.client()
        start = client.get("/calendar/google/authorize")
        state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

        response = client.post(
            "/calendar/google/callback",
            headers={"Origin": "http://attacker.test"},
            json={"code": "one-time-code", "state": state},
        )
        self.assertEqual(response.status_code, 403)

        no_refresh = CalendarGoogleTokenResponse(
            access_token="google-access",
            token_type="Bearer",
            expires_in=3600,
            refresh_token=None,
            scope=GOOGLE_CALENDAR_SCOPE,
        )
        client = self.client(exchange=Mock(return_value=no_refresh))
        start = client.get("/calendar/google/authorize")
        state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
        response = client.post(
            "/calendar/google/callback",
            headers={"Origin": "http://localhost:5173"},
            json={"code": "one-time-code", "state": state},
        )
        self.assertEqual(response.status_code, 401)
        self.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()


"""Calendar 연결은 사용자 로그인 scope 없이 일정 권한만 요청한다."""

import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from backend.calendar_oauth_service import create_calendar_authorization_url
from backend.calendar_service import GOOGLE_CALENDAR_SCOPE


class CalendarOAuthServiceTests(unittest.TestCase):
    def test_authorization_url_requests_calendar_scope_without_login_scopes(self):
        with patch(
            "backend.calendar_oauth_service.get_google_auth_settings",
            return_value=type("Settings", (), {
                "client_id": "client-id",
                "redirect_uri": "http://localhost:5173/calendar-callback.html",
            })(),
        ):
            url = create_calendar_authorization_url("state-value")

        parameters = parse_qs(urlsplit(url).query)
        self.assertEqual(parameters["scope"], [GOOGLE_CALENDAR_SCOPE])
        self.assertNotIn("openid", parameters["scope"][0])
        self.assertNotIn("email", parameters["scope"][0])
        self.assertEqual(parameters["access_type"], ["offline"])
        self.assertEqual(parameters["prompt"], ["consent"])


if __name__ == "__main__":
    unittest.main()


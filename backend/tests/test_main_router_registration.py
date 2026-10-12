"""실제 OpenAPI에는 앱 로그인 대신 공개 추천·Calendar 연결 경로가 보인다."""

import unittest

from backend.main import app


class MainRouterRegistrationTests(unittest.TestCase):
    def test_login_and_server_profile_routes_are_not_registered(self):
        paths = app.openapi()["paths"]

        self.assertNotIn("/auth/google/authorize", paths)
        self.assertNotIn("/auth/google", paths)
        self.assertNotIn("/auth/refresh", paths)
        self.assertNotIn("/auth/logout", paths)
        self.assertNotIn("/me/profile", paths)

    def test_recommendation_and_calendar_only_oauth_routes_are_registered(self):
        paths = app.openapi()["paths"]

        self.assertIn("/recommendations", paths)
        self.assertIn("/interest-categories", paths)
        self.assertIn("/calendar/google/authorize", paths)
        self.assertIn("/calendar/google/callback", paths)
        self.assertIn("/calendar/register", paths)

        recommendation = paths["/recommendations"]["post"]
        self.assertNotIn("security", recommendation)
        self.assertIn("requestBody", recommendation)


if __name__ == "__main__":
    unittest.main()


"""API 입력 검증과 DB 미연결 안내를 확인한다."""

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app


class APITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_documentation_contains_confirmed_routes(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/certificates", schema["paths"])
        self.assertIn("/certificates/{certificate_id}", schema["paths"])
        self.assertIn("/certificates/{certificate_id}/schedules", schema["paths"])
        self.assertFalse(any(path.startswith("/api/") for path in schema["paths"]))
        self.assertIn("ProfilePatch", schema["components"]["schemas"])
        self.assertNotIn("/me/bookmarks", schema["paths"])

    def test_database_not_configured_is_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.client.get("/health").json()["database_configured"])
            self.assertEqual(self.client.get("/certificates").status_code, 503)
            self.assertEqual(self.client.get(f"/certificates/{uuid4()}/schedules?year=2026").status_code, 503)

    def test_pagination_and_date_input_validation(self):
        self.assertEqual(self.client.get("/certificates?limit=101").status_code, 422)
        self.assertEqual(self.client.get("/certificates?offset=-1").status_code, 422)
        self.assertEqual(self.client.get("/certificates/not-a-uuid/schedules?year=2026").status_code, 422)

    def test_search_passes_parameters_and_serializes_uuid(self):
        now = datetime.now(timezone.utc)
        identifier = uuid4()
        row = {"id": identifier, "qnet_code": "0752", "name": "가스기술사", "category": "T",
               "career_tags": [], "description": None, "source_url": "https://www.q-net.or.kr/",
               "last_synced_at": now, "updated_at": now}
        with patch.dict(os.environ, {"DATABASE_URL": "test-not-a-real-connection"}):
            with patch("backend.main.list_certificates", return_value=[row]) as search:
                response = self.client.get("/certificates?q=가스&category=T&limit=5&offset=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["qnet_code"], "0752")
        self.assertEqual(response.json()[0]["id"], str(identifier))
        search.assert_called_once_with("가스", "T", 5, 1)


if __name__ == "__main__":
    unittest.main()

"""설정 파일과 실제 DB 상태 검사의 실패·준비 상태를 검증한다."""

from contextlib import nullcontext
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import psycopg

from backend.db.check import check_database, REQUIRED_TABLES
from backend.main import app
from backend.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_reads_local_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DATABASE_URL=test-file-value\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_settings(path)
                self.assertEqual(os.environ["DATABASE_URL"], "test-file-value")

    def test_existing_environment_has_priority(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DATABASE_URL=test-file-value\n", encoding="utf-8")
            with patch.dict(os.environ, {"DATABASE_URL": "test-environment-value"}):
                load_settings(path)
                self.assertEqual(os.environ["DATABASE_URL"], "test-environment-value")


class DatabaseCheckTests(unittest.TestCase):
    def test_missing_config_does_not_connect(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("backend.db.check.database_connection") as connect:
                result = check_database()
        self.assertEqual(result["status"], "not_configured")
        connect.assert_not_called()

    def test_connection_failure_never_exposes_credentials(self):
        with patch.dict(os.environ, {"DATABASE_URL": "test-secret-connection"}):
            with patch("backend.db.check.database_connection", side_effect=psycopg.OperationalError("test-secret-error")):
                result = check_database()
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["connected"])
        self.assertNotIn("test-secret", str(result))

    def test_connected_but_initial_tables_missing(self):
        connection = Mock()
        connection.execute.return_value.fetchone.side_effect = [{"one": 1}] + [{"relation": None} for _ in REQUIRED_TABLES]
        with patch.dict(os.environ, {"DATABASE_URL": "test-only"}):
            with patch("backend.db.check.database_connection", return_value=nullcontext(connection)):
                result = check_database()
        self.assertTrue(result["connected"])
        self.assertEqual(result["status"], "tables_missing")
        self.assertEqual(result["missing_tables"], list(REQUIRED_TABLES))

    def test_initial_tables_present(self):
        connection = Mock()
        connection.execute.return_value.fetchone.side_effect = [{"one": 1}] + [{"relation": table} for table in REQUIRED_TABLES]
        with patch.dict(os.environ, {"DATABASE_URL": "test-only"}):
            with patch("backend.db.check.database_connection", return_value=nullcontext(connection)):
                result = check_database()
        self.assertTrue(result["tables_ready"])
        self.assertEqual(result["status"], "ready")

    def test_database_health_returns_503_without_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with TestClient(app) as client:
                response = client.get("/health/database")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["connected"])


if __name__ == "__main__":
    unittest.main()

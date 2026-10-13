"""인증 DB 사전 점검이 읽기 전용으로 동작하는지 확인한다."""

from contextlib import nullcontext
import os
import unittest
from unittest.mock import Mock, patch

import psycopg

from backend.db.check_auth import AUTH_REQUIRED_TABLES, check_auth_database


class AuthDatabaseCheckTests(unittest.TestCase):
    def test_missing_connection_setting_does_not_connect(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("backend.db.check_auth.database_connection") as connect:
                result = check_auth_database()

        self.assertEqual(result["status"], "not_configured")
        connect.assert_not_called()

    def test_missing_auth_tables_are_reported_without_writing(self):
        connection = Mock()
        connection.execute.return_value.fetchone.side_effect = (
            [{"one": 1}]
            + [{"relation": "users"}, {"relation": None}, {"relation": None}]
        )
        with patch.dict(os.environ, {"DATABASE_URL": "test-only"}):
            with patch(
                "backend.db.check_auth.database_connection",
                return_value=nullcontext(connection),
            ):
                result = check_auth_database()

        self.assertEqual(result["status"], "tables_missing")
        self.assertEqual(
            result["missing_tables"],
            ["auth_sessions", "auth_refresh_tokens"],
        )
        self.assertEqual(connection.execute.call_count, len(AUTH_REQUIRED_TABLES) + 1)
        for call in connection.execute.call_args_list:
            self.assertTrue(call.args[0].startswith("SELECT"))

    def test_ready_tables_are_reported(self):
        connection = Mock()
        connection.execute.return_value.fetchone.side_effect = (
            [{"one": 1}]
            + [{"relation": table} for table in AUTH_REQUIRED_TABLES]
        )
        with patch.dict(os.environ, {"DATABASE_URL": "test-only"}):
            with patch(
                "backend.db.check_auth.database_connection",
                return_value=nullcontext(connection),
            ):
                result = check_auth_database()

        self.assertTrue(result["tables_ready"])
        self.assertEqual(result["status"], "ready")

    def test_connection_failure_hides_credentials(self):
        with patch.dict(os.environ, {"DATABASE_URL": "secret-connection-url"}):
            with patch(
                "backend.db.check_auth.database_connection",
                side_effect=psycopg.OperationalError("secret-connection-url"),
            ):
                result = check_auth_database()

        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("secret-connection-url", str(result))


if __name__ == "__main__":
    unittest.main()

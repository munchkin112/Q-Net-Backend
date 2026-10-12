"""Calendar 전용 세션은 무작위 쿠키값의 해시와 암호문만 DB에 저장한다."""

import hashlib
import unittest
import os
from unittest.mock import Mock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

from backend.calendar_service import (
    create_calendar_connection,
    get_calendar_connection_credential,
    get_calendar_connection_id,
    GOOGLE_CALENDAR_SCOPE,
)


class CalendarConnectionTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.execute.return_value.fetchone.return_value = {"id": uuid4()}
        self.key = Fernet.generate_key().decode("ascii")

    def test_create_stores_hash_and_encrypted_refresh_token(self):
        with patch.dict(os.environ, {"GOOGLE_TOKEN_ENCRYPTION_KEY": self.key}):
            session_token = create_calendar_connection(
                self.connection,
                "google-refresh-token",
                GOOGLE_CALENDAR_SCOPE,
            )

        query, parameters = self.connection.execute.call_args.args
        self.assertIn("INSERT INTO calendar_connections", query)
        self.assertEqual(parameters[1], hashlib.sha256(session_token.encode()).hexdigest())
        self.assertNotIn(session_token, parameters)
        self.assertNotIn("google-refresh-token", parameters)
        decrypted = Fernet(self.key.encode()).decrypt(parameters[2].encode()).decode()
        self.assertEqual(decrypted, "google-refresh-token")

    def test_lookup_hashes_session_and_returns_connection_id(self):
        connection_id = uuid4()
        self.connection.execute.return_value.fetchone.return_value = {"id": connection_id}

        result = get_calendar_connection_id(self.connection, "opaque-session-token")

        self.assertEqual(result, connection_id)
        query, parameters = self.connection.execute.call_args.args
        self.assertIn("expires_at > now()", query)
        self.assertIn("revoked_at IS NULL", query)
        self.assertEqual(parameters, (hashlib.sha256(b"opaque-session-token").hexdigest(),))

    def test_get_credential_decrypts_only_calendar_scope(self):
        connection_id = uuid4()
        encrypted = Fernet(self.key.encode()).encrypt(b"refresh-token").decode()
        self.connection.execute.return_value.fetchone.return_value = {
            "refresh_token_ciphertext": encrypted,
            "scopes": GOOGLE_CALENDAR_SCOPE,
        }
        with patch.dict(os.environ, {"GOOGLE_TOKEN_ENCRYPTION_KEY": self.key}):
            result = get_calendar_connection_credential(self.connection, connection_id)
        self.assertEqual(result, ("refresh-token", GOOGLE_CALENDAR_SCOPE))


if __name__ == "__main__":
    unittest.main()


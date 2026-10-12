"""Google Calendar 자격 증명의 안전한 저장 동작을 검증한다."""

import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

from backend.calendar_service import create_google_calendar_credential


class GoogleCalendarCredentialTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.user_id = uuid4()
        self.encryption_key = Fernet.generate_key().decode("ascii")

    def test_saves_encrypted_refresh_token_without_committing(self):
        self.connection.execute.return_value.fetchone.return_value = {
            "user_id": self.user_id
        }

        with patch.dict(
            os.environ,
            {"GOOGLE_TOKEN_ENCRYPTION_KEY": self.encryption_key},
        ):
            result = create_google_calendar_credential(
                self.connection,
                self.user_id,
                "google-refresh-token",
                "openid email https://www.googleapis.com/auth/calendar.events.owned",
            )

        self.assertTrue(result)
        query, parameters = self.connection.execute.call_args.args
        self.assertIn("ON CONFLICT (user_id)", query)
        self.assertNotIn("google-refresh-token", str(parameters))
        decrypted_token = Fernet(self.encryption_key.encode("ascii")).decrypt(
            parameters[1].encode("ascii")
        )
        self.assertEqual(decrypted_token.decode("utf-8"), "google-refresh-token")
        expected_scopes = (
            "openid email "
            "https://www.googleapis.com/auth/calendar.events.owned"
        )
        self.assertEqual(parameters[2], expected_scopes)
        self.connection.commit.assert_not_called()

    def test_missing_refresh_token_preserves_token_and_updates_nonempty_scopes(self):
        self.connection.execute.return_value.fetchone.return_value = {
            "user_id": self.user_id
        }
        scopes = "openid email https://www.googleapis.com/auth/calendar.events.owned"

        result = create_google_calendar_credential(
            self.connection,
            self.user_id,
            None,
            scopes,
        )

        self.assertTrue(result)
        query, parameters = self.connection.execute.call_args.args
        self.assertIn("UPDATE google_calendar_credentials", query)
        self.assertIn("COALESCE(NULLIF(btrim(%s), ''), scopes)", query)
        self.assertNotIn("refresh_token_ciphertext =", query)
        self.assertEqual(parameters, (scopes, self.user_id))

    def test_missing_refresh_token_without_saved_credential_returns_false(self):
        self.connection.execute.return_value.fetchone.return_value = None

        result = create_google_calendar_credential(
            self.connection,
            self.user_id,
            None,
            "openid email",
        )

        self.assertFalse(result)
        self.connection.commit.assert_not_called()

    def test_invalid_encryption_key_fails_without_database_access(self):
        with patch.dict(
            os.environ,
            {"GOOGLE_TOKEN_ENCRYPTION_KEY": "not-a-fernet-key"},
        ):
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_TOKEN_ENCRYPTION_KEY"):
                create_google_calendar_credential(
                    self.connection,
                    self.user_id,
                    "google-refresh-token",
                    "openid email",
                )

        self.connection.execute.assert_not_called()

    def test_blank_refresh_token_is_rejected_without_database_access(self):
        with self.assertRaises(ValueError):
            create_google_calendar_credential(
                self.connection,
                self.user_id,
                "   ",
                "openid email",
            )

        self.connection.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

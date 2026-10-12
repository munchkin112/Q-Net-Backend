"""Google Calendar 권한 갱신에 필요한 자격 증명을 저장한다."""

import binascii
import os
from uuid import UUID

from cryptography.fernet import Fernet
from psycopg import Connection

from backend.settings import load_settings


def get_google_token_fernet() -> Fernet:
    """전용 환경변수에서 Google 토큰 암호화 키를 읽는다."""
    load_settings()
    encryption_key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY 환경변수가 필요합니다.")

    try:
        return Fernet(encryption_key.encode("ascii"))
    except (binascii.Error, UnicodeError, TypeError, ValueError):
        raise RuntimeError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY 형식이 올바르지 않습니다."
        ) from None


def create_google_calendar_credential(
    connection: Connection,
    user_id: UUID,
    refresh_token: str | None,
    scopes: str,
) -> bool:
    """Google 갱신 토큰을 암호화 저장하고 Calendar 연결 여부를 반환한다.

    호출자가 전달한 DB 연결을 사용하며 커밋하지 않는다.
    Google이 새 토큰을 반환하지 않으면 기존 저장값을 유지한다.
    """
    if not isinstance(user_id, UUID):
        raise ValueError("Google Calendar 사용자 ID가 유효하지 않습니다.")
    if not isinstance(scopes, str):
        raise ValueError("Google Calendar 권한 정보 형식이 올바르지 않습니다.")

    if refresh_token is None:
        existing_credential = connection.execute(
            """UPDATE google_calendar_credentials
            SET scopes = COALESCE(NULLIF(btrim(%s), ''), scopes),
                updated_at = now()
            WHERE user_id = %s
            RETURNING user_id""",
            (scopes, user_id),
        ).fetchone()
        return existing_credential is not None

    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise ValueError("Google Calendar 갱신 토큰 형식이 올바르지 않습니다.")

    token_cipher = get_google_token_fernet()
    encrypted_refresh_token = token_cipher.encrypt(
        refresh_token.encode("utf-8")
    ).decode("ascii")

    saved_credential = connection.execute(
        """INSERT INTO google_calendar_credentials (
            user_id,
            refresh_token_ciphertext,
            scopes
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            refresh_token_ciphertext = EXCLUDED.refresh_token_ciphertext,
            scopes = EXCLUDED.scopes,
            updated_at = now()
        RETURNING user_id""",
        (user_id, encrypted_refresh_token, scopes),
    ).fetchone()

    return saved_credential is not None

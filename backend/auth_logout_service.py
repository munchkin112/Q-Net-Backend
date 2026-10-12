"""리프레시 쿠키에 연결된 로그인 세션을 종료한다."""

from uuid import UUID

from backend.auth_refresh import validate_refresh_token
from backend.db.auth_refresh_repository import get_auth_refresh_token
from backend.db.auth_session_repository import update_auth_session_revocation
from backend.db.connection import database_connection


def handle_auth_logout(refresh_token: str | None) -> None:
    """현재 로그인 세션을 폐기한다. 쿠키가 없거나 이미 종료됐으면 정상 처리한다."""
    if refresh_token is None:
        return

    try:
        validate_refresh_token(refresh_token)
    except ValueError:
        return

    with database_connection() as connection:
        token_record = get_auth_refresh_token(
            connection, refresh_token,
        )

        if token_record is None:
            return

        required_fields = (
            "session_id",
            "user_id",
            "revoked_at",
        )
        if not isinstance(token_record, dict) or any(
            field not in token_record for field in required_fields
        ):
            raise RuntimeError(
                "로그인 세션 정보를 확인할 수 없습니다."
            )

        session_id = token_record["session_id"]
        user_id = token_record["user_id"]

        if (
            not isinstance(session_id, UUID)
            or not isinstance(user_id, UUID)
        ):
            raise RuntimeError(
                "로그인 세션 정보를 확인할 수 없습니다."
            )

        if token_record["revoked_at"] is not None:
            return

        revoked = update_auth_session_revocation(
            connection, session_id, user_id,
        )

        if not revoked:
            raise RuntimeError(
                "로그인 세션을 종료할 수 없습니다."
            )
"""리프레시 토큰으로 서비스 토큰을 재발급하고, 이전 토큰 재사용 시 세션을 폐기한다."""

from datetime import datetime

from pydantic import BaseModel, Field

from backend.auth_refresh import (
    REFRESH_TOKEN_LENGTH,
    create_refresh_token,
    validate_refresh_token,
)
from backend.auth_schemas import TokenRefreshResponse
from backend.auth_tokens import (
    ACCESS_TOKEN_TTL_SECONDS,
    create_access_token,
    validate_access_token_secret,
)
from backend.db.auth_refresh_repository import (
    create_auth_refresh_token,
    get_auth_refresh_token,
    update_auth_refresh_token_usage,
)
from backend.db.auth_session_repository import (
    update_auth_session_revocation,
    validate_auth_session,
)
from backend.db.connection import database_connection


REFRESH_TOKEN_ERROR_MESSAGE = (
    "로그인 유지 정보가 유효하지 않습니다. 다시 로그인해주세요."
)


class RefreshTokenInvalidError(ValueError):
    """리프레시 토큰 또는 연결된 세션이 유효하지 않다."""


class RefreshTokenReuseError(RefreshTokenInvalidError):
    """이미 사용한 리프레시 토큰이 다시 들어와 로그인 세션을 폐기했다."""


class AuthRefreshResult(BaseModel):
    """API 응답과 쿠키 설정에 사용할 내부 결과다."""

    response: TokenRefreshResponse
    refresh_token: str = Field(
        min_length=REFRESH_TOKEN_LENGTH,
        max_length=REFRESH_TOKEN_LENGTH,
        repr=False,
        exclude=True,
    )
    session_expires_at: datetime | None = Field(exclude=True)


def update_auth_tokens(
    refresh_token: str,
    *,
    secret_key: str,
) -> AuthRefreshResult:
    """기존 만료 정책을 유지하면서 새 액세스·리프레시 토큰을 발급한다."""
    try:
        validate_refresh_token(refresh_token)
    except ValueError:
        raise RefreshTokenInvalidError(
            REFRESH_TOKEN_ERROR_MESSAGE
        ) from None

    validate_access_token_secret(secret_key)
    reused_token = False
    result = None

    with database_connection() as connection:
        token_record = get_auth_refresh_token(
            connection, refresh_token,
        )

        required_fields = (
            "session_id",
            "user_id",
            "expires_at",
            "revoked_at",
            "used_at",
        )
        if not isinstance(token_record, dict) or any(
            field not in token_record for field in required_fields
        ):
            raise RefreshTokenInvalidError(
                REFRESH_TOKEN_ERROR_MESSAGE
            )

        session_id = token_record["session_id"]
        user_id = token_record["user_id"]
        session = {
            "id": session_id,
            "user_id": user_id,
            "expires_at": token_record["expires_at"],
            "revoked_at": token_record["revoked_at"],
        }

        try:
            validate_auth_session(
                session, session_id, user_id,
            )
        except ValueError:
            raise RefreshTokenInvalidError(
                REFRESH_TOKEN_ERROR_MESSAGE
            ) from None

        reused_token = token_record["used_at"] is not None

        if not reused_token:
            reused_token = not update_auth_refresh_token_usage(
                connection, session_id, refresh_token,
            )

        if reused_token:
            revoked = update_auth_session_revocation(
                connection, session_id, user_id,
            )
            if not revoked:
                raise RuntimeError(
                    "로그인 세션을 종료할 수 없습니다."
                )
        else:
            new_refresh_token = create_refresh_token()

            create_auth_refresh_token(
                connection, session_id, new_refresh_token,
            )

            access_token = create_access_token(
                user_id,
                session_id,
                secret_key=secret_key,
            )

            result = AuthRefreshResult(
                response=TokenRefreshResponse(
                    access_token=access_token,
                    expires_in=ACCESS_TOKEN_TTL_SECONDS,
                ),
                refresh_token=new_refresh_token,
                session_expires_at=session["expires_at"],
            )

    # 세션 폐기 기록을 확정한 뒤 오류를 발생시킨다.
    if reused_token:
        raise RefreshTokenReuseError(
            "이전 로그인 유지 토큰이 재사용되어 세션을 종료했습니다. "
            "다시 로그인해주세요."
        )

    if result is None:
        raise RuntimeError(
            "로그인 토큰을 재발급할 수 없습니다."
        )

    return result

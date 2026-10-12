"""액세스 토큰과 로그인 세션을 함께 검사해 인증된 사용자를 조회한다."""

from backend.auth_schemas import AuthUserResponse
from backend.auth_tokens import (
    AccessTokenExpiredError,
    validate_access_token,
)
from backend.db.auth_repository import get_user
from backend.db.auth_session_repository import (
    get_auth_session,
    validate_auth_session,
)
from backend.db.connection import database_connection


class AuthUserInvalidError(ValueError):
    """액세스 토큰 또는 사용자 정보가 유효하지 않다."""


class AuthSessionInvalidError(AuthUserInvalidError):
    """로그인 세션이 없거나 만료·폐기됐거나 토큰의 정보와 일치하지 않는다."""


def get_authenticated_user(
    access_token: str,
    *,
    secret_key: str,
) -> AuthUserResponse:
    """검증된 토큰의 회원·세션 ID로 현재 사용자를 조회한다."""
    try:
        claims = validate_access_token(
            access_token,
            secret_key=secret_key,
        )
    except AccessTokenExpiredError:
        raise
    except ValueError:
        raise AuthUserInvalidError(
            "로그인 토큰이 유효하지 않습니다. 다시 로그인해주세요."
        ) from None

    with database_connection() as connection:
        session = get_auth_session(
            connection,
            claims.session_id,
            claims.user_id,
        )

        try:
            validate_auth_session(
                session,
                claims.session_id,
                claims.user_id,
            )
        except ValueError:
            raise AuthSessionInvalidError(
                "로그인 세션이 유효하지 않습니다. 다시 로그인해주세요."
            ) from None

        user = get_user(connection, claims.user_id)

        if not isinstance(user, dict) or user.get("id") != claims.user_id:
            raise AuthUserInvalidError(
                "사용자 정보를 확인할 수 없습니다. 다시 로그인해주세요."
            )

        return AuthUserResponse(
            id=user["id"],
            email=user.get("email"),
        )
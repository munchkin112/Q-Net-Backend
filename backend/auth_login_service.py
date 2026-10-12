"""검증된 Google 사용자에게 우리 서비스 로그인 세션을 생성한다."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, Field

from backend.auth_identity import GoogleIdentity
from backend.auth_refresh import REFRESH_TOKEN_LENGTH, create_refresh_token
from backend.auth_schemas import AuthUserResponse
from backend.auth_tokens import (
    ACCESS_TOKEN_TTL_SECONDS,
    create_access_token,
    validate_access_token_secret,
)
from backend.db.auth_refresh_repository import create_auth_refresh_token
from backend.db.auth_repository import create_user
from backend.db.auth_session_repository import create_auth_session
from backend.db.connection import database_connection


AUTH_SESSION_MAX_DAYS = 7


class GoogleLoginSessionResult(BaseModel):
    """로그인 API에서 응답·쿠키 설정에 사용할 내부 결과다."""

    user: AuthUserResponse
    access_token: str = Field(min_length=1, repr=False)
    refresh_token: str = Field(
        min_length=REFRESH_TOKEN_LENGTH,
        max_length=REFRESH_TOKEN_LENGTH,
        repr=False,
        exclude=True,
    )
    expires_in: int = Field(gt=0)
    session_expires_at: datetime = Field(exclude=True)


def create_google_login_session(
    identity: GoogleIdentity,
    *,
    secret_key: str,
) -> GoogleLoginSessionResult:
    """검증된 Google 신원으로 사용자·세션·토큰을 한 트랜잭션에서 저장한다."""
    if not isinstance(identity, GoogleIdentity):
        raise ValueError("검증된 Google 사용자 정보가 필요합니다.")

    validate_access_token_secret(secret_key)

    session_expires_at = datetime.now(timezone.utc) + timedelta(
        days=AUTH_SESSION_MAX_DAYS
    )

    with database_connection() as connection:
        user = create_user(connection, identity)

        if not isinstance(user, dict) or not isinstance(user.get("id"), UUID):
            raise RuntimeError("사용자 정보를 저장할 수 없습니다.")

        user_id = user["id"]
        session = create_auth_session(
            connection,
            user_id,
            session_expires_at,
        )

        if (
            not isinstance(session, dict)
            or not isinstance(session.get("id"), UUID)
            or session.get("user_id") != user_id
            or not isinstance(session.get("expires_at"), datetime)
            or session["expires_at"].utcoffset() is None
        ):
            raise RuntimeError("로그인 세션을 저장할 수 없습니다.")

        session_id = session["id"]
        refresh_token = create_refresh_token()
        create_auth_refresh_token(
            connection,
            session_id,
            refresh_token,
        )

        access_token = create_access_token(
            user_id,
            session_id,
            secret_key=secret_key,
        )

        result = GoogleLoginSessionResult(
            user=AuthUserResponse(
                id=user_id,
                email=user.get("email"),
            ),
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            session_expires_at=session["expires_at"],
        )

    return result
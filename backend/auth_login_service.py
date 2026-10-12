"""검증된 Google 사용자에게 우리 서비스 로그인 세션을 생성한다."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from psycopg import Connection
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


CalendarCredentialCreator = Callable[
    [Connection, UUID, str | None, str],
    bool,
]


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
    session_expires_at: datetime | None = Field(exclude=True)
    calendar_connected: bool


def create_google_login_session(
    identity: GoogleIdentity,
    *,
    secret_key: str,
    google_refresh_token: str | None,
    google_scopes: str,
    calendar_credential_creator: CalendarCredentialCreator,
) -> GoogleLoginSessionResult:
    """사용자·캘린더 자격 증명·로그인 세션을 한 DB 트랜잭션에서 저장한다."""
    if not isinstance(identity, GoogleIdentity):
        raise ValueError("검증된 Google 사용자 정보가 필요합니다.")
    if google_refresh_token is not None and (
        not isinstance(google_refresh_token, str)
        or not google_refresh_token.strip()
    ):
        raise ValueError("Google Calendar 토큰 형식이 올바르지 않습니다.")
    if not isinstance(google_scopes, str):
        raise ValueError("Google 권한 정보 형식이 올바르지 않습니다.")
    if not callable(calendar_credential_creator):
        raise ValueError("Google Calendar 저장 함수가 필요합니다.")

    validate_access_token_secret(secret_key)

    session_expires_at = None

    with database_connection() as connection:
        user = create_user(connection, identity)

        if not isinstance(user, dict) or not isinstance(user.get("id"), UUID):
            raise RuntimeError("사용자 정보를 저장할 수 없습니다.")

        user_id = user["id"]

        # 저장 함수는 커밋하지 않는다. 이 서비스의 DB 연결이 최종 커밋을 맡는다.
        calendar_connected = calendar_credential_creator(
            connection,
            user_id,
            google_refresh_token,
            google_scopes,
        )
        if not isinstance(calendar_connected, bool):
            raise RuntimeError("Google Calendar 연결 상태를 확인할 수 없습니다.")

        session = create_auth_session(
            connection,
            user_id,
            session_expires_at,
        )

        if (
            not isinstance(session, dict)
            or not isinstance(session.get("id"), UUID)
            or session.get("user_id") != user_id
            or (
                session.get("expires_at") is not None
                and (
                    not isinstance(session["expires_at"], datetime)
                    or session["expires_at"].utcoffset() is None
                )
            )
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
            session_expires_at=session.get("expires_at"),
            calendar_connected=calendar_connected,
        )

    return result

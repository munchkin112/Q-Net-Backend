"""Calendar 전용 HttpOnly 쿠키로 연결 세션을 검증한다."""

import psycopg
from fastapi import Cookie, HTTPException
from uuid import UUID

from backend.calendar_oauth_router import CALENDAR_SESSION_COOKIE_NAME
from backend.calendar_service import get_calendar_connection_id
from backend.db.connection import database_connection


def require_calendar_connection(
    session_token: str | None = Cookie(default=None, alias=CALENDAR_SESSION_COOKIE_NAME),
) -> UUID:
    """앱 로그인 대신 Calendar 권한 쿠키가 유효한지 확인한다."""
    if not session_token:
        raise HTTPException(
            401,
            detail={"code": "CALENDAR_CONNECTION_REQUIRED", "message": "먼저 Google Calendar를 연결해주세요."},
        )

    try:
        with database_connection() as connection:
            connection_id = get_calendar_connection_id(connection, session_token)
    except (psycopg.Error, RuntimeError):
        raise HTTPException(
            503,
            detail={"code": "CALENDAR_CONNECTION_UNAVAILABLE", "message": "Calendar 연결을 확인할 수 없습니다."},
        ) from None

    if connection_id is None:
        raise HTTPException(
            401,
            detail={"code": "CALENDAR_CONNECTION_EXPIRED", "message": "Calendar 연결이 만료되었습니다. 다시 연결해주세요."},
        )
    return connection_id


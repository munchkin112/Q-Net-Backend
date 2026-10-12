"""사용자 로그인 없이 Google Calendar 연결·해제를 제공한다."""

from collections.abc import Callable

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.auth_state import (
    OAUTH_STATE_TTL_SECONDS,
    create_google_oauth_transaction,
    validate_google_oauth_state,
)
from backend.calendar_oauth_service import (
    CalendarGoogleTokenResponse,
    create_calendar_authorization_url,
    exchange_calendar_code,
)
from backend.calendar_service import (
    CALENDAR_SESSION_TTL_SECONDS,
    create_calendar_connection,
)
from backend.browser_settings import get_allowed_origins, get_cookie_secure
from backend.db.connection import database_connection


CALENDAR_OAUTH_COOKIE_NAME = "qnet_calendar_oauth"
CALENDAR_SESSION_COOKIE_NAME = "qnet_calendar_session"
CALENDAR_OAUTH_COOKIE_PATH = "/calendar/google"
CALENDAR_SESSION_COOKIE_PATH = "/calendar"


class CalendarOAuthRequest(BaseModel):
    """프론트 콜백이 Google 인증 코드와 state를 전달한다."""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, repr=False)
    state: str = Field(min_length=1, repr=False)


class CalendarAuthorizeResponse(BaseModel):
    """브라우저가 Google Calendar 동의 화면으로 이동할 URL이다."""

    authorization_url: str


class CalendarConnectionResponse(BaseModel):
    """Calendar 전용 권한이 연결되었음을 알린다."""

    calendar_connected: bool = True
    expires_in: int = Field(gt=0)


def _store_calendar_connection(refresh_token: str, scopes: str) -> str:
    """암호화된 Google 토큰과 해시된 Calendar 세션을 저장한다."""
    with database_connection() as connection:
        return create_calendar_connection(connection, refresh_token, scopes)


def create_calendar_oauth_router(
    make_authorization_url: Callable = create_calendar_authorization_url,
    exchange_code: Callable = exchange_calendar_code,
    save_connection: Callable = _store_calendar_connection,
    read_allowed_origins: Callable = get_allowed_origins,
    read_cookie_secure: Callable = get_cookie_secure,
) -> APIRouter:
    """Calendar 권한 전용 OAuth 경로를 만든다. 서비스 로그인은 발급하지 않는다."""
    router = APIRouter(prefix="/calendar/google", tags=["Google Calendar 연결"])

    @router.get(
        "/authorize",
        response_model=CalendarAuthorizeResponse,
        summary="Google Calendar 연결 시작 주소 생성",
        responses={503: {"description": "Google 설정 또는 OAuth 요청 확인 필요"}},
    )
    def get_calendar_authorization(response: Response) -> CalendarAuthorizeResponse:
        """Calendar 일정 관리 권한만 요청하고 state 확인 쿠키를 설정한다."""
        try:
            cookie_secure = read_cookie_secure()
            state, browser_token = create_google_oauth_transaction()
            authorization_url = make_authorization_url(state)
        except (RuntimeError, ValueError):
            raise HTTPException(
                503,
                detail={"code": "CALENDAR_OAUTH_UNAVAILABLE", "message": "Calendar 연결을 시작할 수 없습니다."},
            ) from None

        response.set_cookie(
            key=CALENDAR_OAUTH_COOKIE_NAME,
            value=browser_token,
            max_age=OAUTH_STATE_TTL_SECONDS,
            path=CALENDAR_OAUTH_COOKIE_PATH,
            secure=cookie_secure,
            httponly=True,
            samesite="none" if cookie_secure else "lax",
        )
        response.headers["Cache-Control"] = "no-store"
        return CalendarAuthorizeResponse(authorization_url=authorization_url)

    @router.post(
        "/callback",
        response_model=CalendarConnectionResponse,
        summary="Google Calendar 권한 동의 완료",
        responses={
            400: {"description": "Google 권한 교환 실패"},
            401: {"description": "OAuth state 또는 Calendar 동의 확인 필요"},
            403: {"description": "허용되지 않은 프론트 주소"},
            503: {"description": "설정·DB·토큰 저장 확인 필요"},
        },
    )
    def complete_calendar_authorization(
        oauth_request: CalendarOAuthRequest,
        request: Request,
        response: Response,
    ) -> CalendarConnectionResponse:
        """Google 토큰을 저장하고 Calendar 전용 세션 쿠키를 발급한다."""
        try:
            allowed_origins = read_allowed_origins()
            cookie_secure = read_cookie_secure()
        except RuntimeError:
            raise HTTPException(
                503,
                detail={"code": "CALENDAR_OAUTH_UNAVAILABLE", "message": "Calendar 연결 설정을 확인해주세요."},
            ) from None

        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(
                403,
                detail={"code": "ORIGIN_FORBIDDEN", "message": "허용되지 않은 주소에서 보낸 요청입니다."},
            )

        try:
            validate_google_oauth_state(
                oauth_request.state,
                request.cookies.get(CALENDAR_OAUTH_COOKIE_NAME),
            )
        except ValueError:
            raise HTTPException(
                401,
                detail={"code": "CALENDAR_STATE_INVALID", "message": "Calendar 연결 요청이 만료되었습니다. 다시 시작해주세요."},
            ) from None

        try:
            google_tokens: CalendarGoogleTokenResponse = exchange_code(oauth_request.code)
        except (ValueError, RuntimeError):
            raise HTTPException(
                400,
                detail={"code": "GOOGLE_CALENDAR_AUTHORIZATION_FAILED", "message": "Google Calendar 동의를 완료하지 못했습니다."},
            ) from None

        if not google_tokens.refresh_token:
            raise HTTPException(
                401,
                detail={"code": "GOOGLE_CALENDAR_PERMISSION_REQUIRED", "message": "오프라인 Calendar 권한 동의가 필요합니다. 다시 연결해주세요."},
            )

        try:
            session_token = save_connection(google_tokens.refresh_token, google_tokens.scope)
        except PermissionError:
            raise HTTPException(
                401,
                detail={"code": "GOOGLE_CALENDAR_PERMISSION_REQUIRED", "message": "Calendar 일정 관리 권한을 허용해주세요."},
            ) from None
        except (RuntimeError, ValueError, psycopg.Error):
            raise HTTPException(
                503,
                detail={"code": "CALENDAR_CONNECTION_UNAVAILABLE", "message": "Calendar 연결을 저장할 수 없습니다."},
            ) from None

        response.set_cookie(
            key=CALENDAR_SESSION_COOKIE_NAME,
            value=session_token,
            max_age=CALENDAR_SESSION_TTL_SECONDS,
            path=CALENDAR_SESSION_COOKIE_PATH,
            secure=cookie_secure,
            httponly=True,
            samesite="none" if cookie_secure else "lax",
        )
        response.delete_cookie(
            key=CALENDAR_OAUTH_COOKIE_NAME,
            path=CALENDAR_OAUTH_COOKIE_PATH,
            secure=cookie_secure,
            httponly=True,
            samesite="none" if cookie_secure else "lax",
        )
        response.headers["Cache-Control"] = "no-store"
        return CalendarConnectionResponse(expires_in=CALENDAR_SESSION_TTL_SECONDS)

    return router


calendar_oauth_router = create_calendar_oauth_router()


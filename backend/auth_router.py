"""Google 로그인과 서비스 세션의 인증 API를 제공한다."""

import os
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from backend.auth_google import fetch_google_tokens
from backend.auth_identity import validate_google_id_token
from backend.auth_login_service import (
    CalendarCredentialCreator,
    create_google_login_session,
)
from backend.auth_refresh_service import (
    RefreshTokenInvalidError,
    update_auth_tokens,
)
from backend.auth_schemas import (
    GoogleAuthorizeResponse,
    GoogleLoginRequest,
    GoogleLoginResponse,
    TokenRefreshResponse,
)
from backend.auth_service import create_google_authorization_url
from backend.auth_settings import get_google_auth_settings
from backend.auth_state import (
    OAUTH_STATE_TTL_SECONDS,
    create_google_oauth_transaction,
    validate_google_oauth_state,
)
from backend.auth_token_settings import get_auth_token_settings
from backend.auth_logout_service import handle_auth_logout


GOOGLE_OAUTH_COOKIE_NAME = "qnet_google_oauth"
GOOGLE_OAUTH_COOKIE_PATH = "/auth/google"

auth_router = APIRouter(prefix="/auth", tags=["Google 로그인"])


def get_auth_cookie_secure() -> bool:
    """기본은 HTTPS 전용이며 로컬 HTTP 개발 때만 false로 설정한다."""
    setting_value = os.environ.get("AUTH_COOKIE_SECURE", "true").strip().lower()

    if setting_value not in {"true", "false"}:
        raise RuntimeError("AUTH_COOKIE_SECURE는 true 또는 false여야 합니다.")

    return setting_value == "true"


@auth_router.get(
    "/google/authorize",
    response_model=GoogleAuthorizeResponse,
    summary="Google 로그인 시작 주소 생성",
    responses={503: {"description": "로그인 설정 또는 요청 처리 확인 필요"}},
)
def get_google_authorization(response: Response) -> GoogleAuthorizeResponse:
    """로그인 주소를 반환하고 요청 확인값은 HttpOnly 쿠키에만 넣는다."""
    try:
        cookie_secure = get_auth_cookie_secure()
        state, browser_token = create_google_oauth_transaction()
        authorization_url = create_google_authorization_url(state)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="로그인을 시작할 수 없습니다. 서버 설정을 확인해주세요.",
        ) from None

    response.set_cookie(
        key=GOOGLE_OAUTH_COOKIE_NAME,
        value=browser_token,
        max_age=OAUTH_STATE_TTL_SECONDS,
        path=GOOGLE_OAUTH_COOKIE_PATH,
        secure=cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"

    return GoogleAuthorizeResponse(authorization_url=authorization_url)

AUTH_REFRESH_COOKIE_NAME = "qnet_refresh_token"
AUTH_REFRESH_COOKIE_PATH = "/auth"
AUTH_REFRESH_COOKIE_TTL_SECONDS = 30 * 24 * 60 * 60


def get_calendar_credential_creator() -> CalendarCredentialCreator:
    """Calendar 담당자가 구현한 저장 함수를 로그인 시점에 불러온다."""
    try:
        from backend.calendar_service import create_google_calendar_credential
    except ImportError:
        raise RuntimeError("Google Calendar 자격 증명 저장 함수가 필요합니다.") from None

    if not callable(create_google_calendar_credential):
        raise RuntimeError("Google Calendar 자격 증명 저장 함수가 필요합니다.")

    return create_google_calendar_credential


def set_auth_refresh_cookie(
    response: Response,
    refresh_token: str,
    session_expires_at: datetime | None,
    *,
    cookie_secure: bool,
) -> None:
    """고정 세션 만료가 없으면 30일 만료 쿠키를 갱신 때마다 다시 설정한다."""
    cookie_options: dict[str, object] = {
        "key": AUTH_REFRESH_COOKIE_NAME,
        "value": refresh_token,
        "path": AUTH_REFRESH_COOKIE_PATH,
        "secure": cookie_secure,
        "httponly": True,
        "samesite": "lax",
    }
    if session_expires_at is not None:
        expires_at = session_expires_at.astimezone(timezone.utc)
        cookie_options["max_age"] = max(
            0,
            int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        )
        cookie_options["expires"] = expires_at
    else:
        cookie_options["max_age"] = AUTH_REFRESH_COOKIE_TTL_SECONDS

    response.set_cookie(
        **cookie_options,
    )


def get_auth_allowed_origins() -> set[str]:
    """쿠키 인증 요청을 허용할 프론트 주소 목록을 환경설정에서 읽는다."""
    origins = {
        value.strip()
        for value in os.environ.get("AUTH_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    error_message = (
        "AUTH_ALLOWED_ORIGINS에는 경로 없는 http/https 프론트 주소가 필요합니다."
    )
    if not origins:
        raise RuntimeError(error_message)

    for origin in origins:
        try:
            parts = urlsplit(origin)
            port = parts.port
        except ValueError:
            raise RuntimeError(error_message) from None

        if (
            "*" in origin
            or parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path
            or parts.query
            or parts.fragment
            or port == 0
        ):
            raise RuntimeError(error_message)

    return origins


def create_auth_error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    clear_refresh_cookie: bool = False,
    cookie_secure: bool = True,
) -> JSONResponse:
    """인증 오류 응답을 만들고, 필요한 경우 리프레시 쿠키를 삭제한다."""
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": [],
                "retryable": status_code >= 500,
            },
            "request_id": str(uuid4()),
        },
        headers={"Cache-Control": "no-store"},
    )

    if clear_refresh_cookie:
        response.delete_cookie(
            key=AUTH_REFRESH_COOKIE_NAME,
            path=AUTH_REFRESH_COOKIE_PATH,
            secure=cookie_secure,
            httponly=True,
            samesite="lax",
        )

    return response


@auth_router.post(
    "/google",
    response_model=GoogleLoginResponse,
    summary="Google 로그인 완료",
    responses={
        400: {"description": "Google 인증 코드 교환 실패"},
        401: {"description": "로그인 요청 또는 Google 사용자 검증 실패"},
        403: {"description": "허용되지 않은 요청 출처"},
        503: {"description": "인증 설정·Calendar 저장 함수·DB 확인 필요"},
    },
)
def create_google_login(
    login_request: GoogleLoginRequest,
    request: Request,
    response: Response,
) -> GoogleLoginResponse | JSONResponse:
    """Google 응답을 검증하고 사용자·Calendar 권한·세션을 저장한다."""
    try:
        cookie_secure = get_auth_cookie_secure()
        allowed_origins = get_auth_allowed_origins()
        get_google_auth_settings()
        token_settings = get_auth_token_settings()
    except RuntimeError:
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "인증 서버 설정을 확인해주세요.",
        )

    if request.headers.get("origin") not in allowed_origins:
        return create_auth_error_response(
            403,
            "AUTH_ORIGIN_FORBIDDEN",
            "허용되지 않은 주소에서 보낸 요청입니다.",
        )

    try:
        calendar_credential_creator = get_calendar_credential_creator()
    except RuntimeError:
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "Google Calendar 저장 기능을 사용할 수 없습니다.",
        )

    try:
        validate_google_oauth_state(
            login_request.state,
            request.cookies.get(GOOGLE_OAUTH_COOKIE_NAME),
        )
    except ValueError:
        return create_auth_error_response(
            401,
            "GOOGLE_STATE_INVALID",
            "로그인 요청이 유효하지 않습니다. 다시 로그인해주세요.",
        )

    try:
        google_tokens = fetch_google_tokens(login_request.code)
    except (ValueError, RuntimeError):
        return create_auth_error_response(
            400,
            "GOOGLE_AUTHORIZATION_FAILED",
            "Google 로그인을 완료할 수 없습니다. 다시 로그인해주세요.",
        )

    try:
        identity = validate_google_id_token(google_tokens.id_token)
    except ValueError:
        return create_auth_error_response(
            401,
            "GOOGLE_ID_TOKEN_INVALID",
            "Google 사용자 정보를 확인할 수 없습니다. 다시 로그인해주세요.",
        )
    except RuntimeError:
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "Google 사용자 정보를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    try:
        result = create_google_login_session(
            identity,
            secret_key=token_settings.access_token_secret,
            google_refresh_token=google_tokens.refresh_token,
            google_scopes=google_tokens.scope,
            calendar_credential_creator=calendar_credential_creator,
        )
    except (RuntimeError, ValueError, psycopg.Error):
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "로그인 정보를 저장할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    set_auth_refresh_cookie(
        response,
        result.refresh_token,
        result.session_expires_at,
        cookie_secure=cookie_secure,
    )
    response.delete_cookie(
        key=GOOGLE_OAUTH_COOKIE_NAME,
        path=GOOGLE_OAUTH_COOKIE_PATH,
        secure=cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"

    return GoogleLoginResponse(
        user=result.user,
        profile_completed=False,
        calendar_connected=result.calendar_connected,
        access_token=result.access_token,
        expires_in=result.expires_in,
    )


@auth_router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    summary="서비스 액세스 토큰 갱신",
    responses={
        401: {"description": "로그인 유지 정보가 유효하지 않음"},
        403: {"description": "허용되지 않은 요청 출처"},
        503: {"description": "인증 설정 또는 DB 확인 필요"},
    },
)
def update_auth_refresh(
    request: Request,
    response: Response,
) -> TokenRefreshResponse | JSONResponse:
    """허용한 프론트의 쿠키를 검증하고 새 액세스 토큰과 리프레시 쿠키를 제공한다."""
    try:
        cookie_secure = get_auth_cookie_secure()
        allowed_origins = get_auth_allowed_origins()
    except RuntimeError:
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "인증 서버 설정을 확인해주세요.",
        )

    if request.headers.get("origin") not in allowed_origins:
        return create_auth_error_response(
            403,
            "AUTH_ORIGIN_FORBIDDEN",
            "허용되지 않은 주소에서 보낸 요청입니다.",
        )

    refresh_token = request.cookies.get(AUTH_REFRESH_COOKIE_NAME)

    if not refresh_token:
        return create_auth_error_response(
            401,
            "REFRESH_TOKEN_INVALID",
            "로그인 유지 정보가 없습니다. 다시 로그인해주세요.",
            clear_refresh_cookie=True,
            cookie_secure=cookie_secure,
        )

    try:
        token_settings = get_auth_token_settings()
        result = update_auth_tokens(
            refresh_token,
            secret_key=token_settings.access_token_secret,
        )
    except RefreshTokenInvalidError:
        return create_auth_error_response(
            401,
            "REFRESH_TOKEN_INVALID",
            "로그인 유지 정보가 유효하지 않습니다. 다시 로그인해주세요.",
            clear_refresh_cookie=True,
            cookie_secure=cookie_secure,
        )
    except (RuntimeError, psycopg.Error):
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "로그인을 갱신할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    set_auth_refresh_cookie(
        response,
        result.refresh_token,
        result.session_expires_at,
        cookie_secure=cookie_secure,
    )
    response.headers["Cache-Control"] = "no-store"

    return result.response

@auth_router.post(
    "/logout",
    status_code=204,
    response_class=Response,
    response_model=None,
    summary="서비스 로그아웃",
    responses={
        403: {"description": "허용되지 않은 요청 출처"},
        503: {"description": "인증 설정 또는 DB 확인 필요"},
    },
)
def handle_auth_logout_request(request: Request) -> Response:
    """현재 로그인 세션을 종료하고 리프레시 쿠키를 삭제한다."""
    try:
        cookie_secure = get_auth_cookie_secure()
        allowed_origins = get_auth_allowed_origins()
    except RuntimeError:
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "인증 서버 설정을 확인해주세요.",
        )

    if request.headers.get("origin") not in allowed_origins:
        return create_auth_error_response(
            403,
            "AUTH_ORIGIN_FORBIDDEN",
            "허용되지 않은 주소에서 보낸 요청입니다.",
        )

    refresh_token = request.cookies.get(AUTH_REFRESH_COOKIE_NAME)

    try:
        handle_auth_logout(refresh_token)
    except (RuntimeError, psycopg.Error):
        return create_auth_error_response(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "로그아웃을 처리할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    response = Response(status_code=204)
    response.delete_cookie(
        key=AUTH_REFRESH_COOKIE_NAME,
        path=AUTH_REFRESH_COOKIE_PATH,
        secure=cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"

    return response

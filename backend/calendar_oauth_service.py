"""Google Calendar 전용 OAuth 주소와 인증 코드를 처리한다."""

from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.auth_settings import get_google_auth_settings
from backend.auth_google import GOOGLE_TOKEN_TIMEOUT_SECONDS, GOOGLE_TOKEN_URL
from backend.calendar_service import GOOGLE_CALENDAR_SCOPE


GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"


class CalendarGoogleTokenResponse(BaseModel):
    """Calendar 권한 동의 후 Google이 반환한 토큰이다."""

    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=1, repr=False)
    token_type: str = Field(min_length=1)
    expires_in: int = Field(gt=0, strict=True)
    refresh_token: str | None = Field(default=None, min_length=1, repr=False)
    scope: str = ""


def create_calendar_authorization_url(state: str) -> str:
    """로그인 정보 없이 Calendar 일정 관리 권한만 요청한다."""
    if not isinstance(state, str) or not state.strip():
        raise ValueError("Google Calendar 연결 state가 필요합니다.")

    settings = get_google_auth_settings()
    parameters = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_CALENDAR_SCOPE,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    return GOOGLE_AUTHORIZATION_URL + "?" + urlencode(parameters)


def exchange_calendar_code(
    code: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> CalendarGoogleTokenResponse:
    """Google 인증 코드를 Calendar 권한 토큰으로 교환한다."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Google Calendar 인증 코드가 필요합니다.")

    settings = get_google_auth_settings()
    try:
        with httpx.Client(
            timeout=GOOGLE_TOKEN_TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
        ) as client:
            response = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "redirect_uri": settings.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError("Google Calendar 응답이 지연되었습니다. 다시 연결해주세요.") from None
    except httpx.HTTPError:
        raise RuntimeError("Google Calendar 권한 교환에 실패했습니다. 다시 연결해주세요.") from None

    try:
        tokens = CalendarGoogleTokenResponse.model_validate(response.json())
    except ValueError:
        raise RuntimeError("Google Calendar 응답 형식을 확인할 수 없습니다.") from None

    if tokens.token_type.lower() != "bearer":
        raise RuntimeError("지원하지 않는 Google 토큰 형식입니다.")
    return tokens


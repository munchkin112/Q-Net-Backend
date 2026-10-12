"""Google 로그인 요청에 사용할 state와 인증 주소를 생성한다."""

import secrets
from urllib.parse import urlencode

from backend.auth_settings import get_google_auth_settings


GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"

GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events.owned",
)


def create_google_oauth_state() -> str:
    """로그인 요청을 구분할 예측하기 어려운 무작위 값을 생성한다."""
    return secrets.token_urlsafe(32)


def create_google_authorization_url(state: str) -> str:
    """서버에 설정된 콜백 주소와 요청 권한으로 Google 인증 주소를 만든다."""
    if not isinstance(state, str) or not state.strip():
        raise ValueError("Google 로그인 요청의 state가 필요합니다.")

    google_settings = get_google_auth_settings()

    parameters = {
        "client_id": google_settings.client_id,
        "redirect_uri": google_settings.redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        # 개발 중에는 권한 동의 화면을 명시적으로 표시한다.
        "prompt": "consent",
    }

    return GOOGLE_AUTHORIZATION_URL + "?" + urlencode(parameters)
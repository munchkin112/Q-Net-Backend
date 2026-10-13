"""Google 인증 코드를 토큰으로 교환하며, 결과는 백엔드 내부에서만 사용한다."""

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.auth_settings import get_google_auth_settings


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKEN_TIMEOUT_SECONDS = 10.0


class GoogleTokenResponse(BaseModel):
    """Google 토큰 응답이다. ID 토큰의 서명 검증은 별도 단계에서 수행한다."""

    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=1, repr=False)
    token_type: str = Field(min_length=1)
    expires_in: int = Field(gt=0, strict=True)
    id_token: str = Field(min_length=1, repr=False)
    refresh_token: str | None = Field(default=None, min_length=1, repr=False)
    scope: str = ""


def fetch_google_tokens(
    code: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> GoogleTokenResponse:
    """검증된 로그인 요청의 code를 교환한다. transport는 모의 테스트용이다."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Google 인증 코드가 필요합니다.")

    google_settings = get_google_auth_settings()

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
                    "client_id": google_settings.client_id,
                    "client_secret": google_settings.client_secret,
                    "redirect_uri": google_settings.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        # 일회용 code는 자동 재시도하지 않고 로그인을 다시 시작한다.
        raise RuntimeError(
            "Google 인증 응답이 지연되었습니다. 로그인을 다시 시작해주세요."
        ) from None
    except httpx.HTTPError:
        raise RuntimeError(
            "Google 인증 코드 교환에 실패했습니다. 로그인을 다시 시작해주세요."
        ) from None

    try:
        tokens = GoogleTokenResponse.model_validate(response.json())
    except ValueError:
        # 검증 오류에 포함될 수 있는 원본 토큰 응답을 외부에 노출하지 않는다.
        raise RuntimeError("Google 인증 응답 형식을 확인할 수 없습니다.") from None

    if tokens.token_type.lower() != "bearer":
        raise RuntimeError("지원하지 않는 Google 토큰 형식입니다.")

    return tokens
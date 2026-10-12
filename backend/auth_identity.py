"""Google ID 토큰을 검증하고 백엔드에서 사용할 사용자 식별정보를 반환한다."""

from functools import partial

import requests
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel, Field

from backend.auth_settings import get_google_auth_settings


GOOGLE_ID_TOKEN_TIMEOUT_SECONDS = 10.0


class GoogleIdentity(BaseModel):
    """검증된 Google 고유 식별값과 확인된 이메일만 보관한다."""

    provider_subject_id: str = Field(min_length=1, max_length=255, repr=False)
    email: str | None = Field(default=None, repr=False)


def validate_google_id_token(token: str) -> GoogleIdentity:
    """공식 라이브러리로 서명·발급자·대상·만료를 검사하고 sub를 반환한다."""
    error_message = "Google 로그인 정보를 확인할 수 없습니다. 다시 로그인해주세요."

    if not isinstance(token, str) or not token.strip():
        raise ValueError(error_message)

    google_settings = get_google_auth_settings()

    try:
        with requests.Session() as session:
            # Google 공개키 조회에 사용할 요청의 대기 시간을 제한한다.
            certificate_request = partial(
                GoogleAuthRequest(session=session),
                timeout=GOOGLE_ID_TOKEN_TIMEOUT_SECONDS,
            )
            claims = google_id_token.verify_oauth2_token(
                token,
                certificate_request,
                audience=google_settings.client_id,
                clock_skew_in_seconds=0,
            )
    except (TransportError, requests.exceptions.RequestException):
        raise RuntimeError(
            "Google 검증 정보를 가져올 수 없습니다. 잠시 후 다시 로그인해주세요."
        ) from None
    except (ValueError, GoogleAuthError, KeyError):
        # 라이브러리 오류의 원본 토큰이나 상세 내용을 외부에 노출하지 않는다.
        raise ValueError(error_message) from None

    if not isinstance(claims, dict):
        raise ValueError(error_message)

    subject_id = claims.get("sub")
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ValueError(error_message)
    if subject_id != subject_id.strip():
        raise ValueError(error_message)

    email = None
    google_email = claims.get("email")
    if claims.get("email_verified") is True and isinstance(google_email, str):
        email = google_email.strip() or None

    try:
        return GoogleIdentity(provider_subject_id=subject_id, email=email)
    except ValueError:
        raise ValueError(error_message) from None
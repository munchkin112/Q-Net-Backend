"""우리 서비스의 액세스 토큰 서명 키를 환경설정에서 읽고 검사한다."""

import os

from pydantic import BaseModel, Field

from backend.auth_tokens import (
    MIN_ACCESS_TOKEN_SECRET_LENGTH,
    validate_access_token_secret,
)
from backend.settings import load_settings


class AuthTokenSettings(BaseModel):
    """서비스 토큰 발급·검증에 사용할 서버 내부 설정이다."""

    access_token_secret: str = Field(
        min_length=MIN_ACCESS_TOKEN_SECRET_LENGTH,
        repr=False,
        exclude=True,
    )


def get_auth_token_settings() -> AuthTokenSettings:
    """기존 설정 로더를 사용해 서명 키를 읽는다. 오류에 키의 실제 값을 넣지 않는다."""
    load_settings()
    secret_key = os.environ.get("AUTH_ACCESS_TOKEN_SECRET", "")

    if not secret_key:
        raise RuntimeError(
            "AUTH_ACCESS_TOKEN_SECRET 설정이 필요합니다."
        )

    try:
        validate_access_token_secret(secret_key)
    except RuntimeError:
        raise RuntimeError(
            "AUTH_ACCESS_TOKEN_SECRET은 "
            "32자 이상의 별도 무작위 서명 키여야 합니다."
        ) from None

    return AuthTokenSettings(access_token_secret=secret_key)
"""Google 로그인에 필요한 환경설정을 읽고 필수값을 검사한다."""

import os

from pydantic import BaseModel, Field

from backend.settings import load_settings


class GoogleAuthSettings(BaseModel):
    """백엔드 내부에서만 사용할 Google OAuth 설정이다."""

    client_id: str = Field(min_length=1, repr=False)
    client_secret: str = Field(min_length=1, repr=False)
    redirect_uri: str = Field(min_length=1)


def get_google_auth_settings() -> GoogleAuthSettings:
    """기존 설정 로더를 재사용하고, 비밀값 없이 누락된 항목만 안내한다."""
    load_settings()

    required_names = (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
    )
    settings_values = {
        name: os.environ.get(name, "").strip()
        for name in required_names
    }
    missing_names = [
        name for name in required_names
        if not settings_values[name]
    ]

    if missing_names:
        raise RuntimeError(
            "Google 로그인 설정이 누락되었습니다: "
            + ", ".join(missing_names)
        )

    return GoogleAuthSettings(
        client_id=settings_values["GOOGLE_CLIENT_ID"],
        client_secret=settings_values["GOOGLE_CLIENT_SECRET"],
        redirect_uri=settings_values["GOOGLE_REDIRECT_URI"],
    )
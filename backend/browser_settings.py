"""브라우저 API 요청에 사용하는 Origin·쿠키 설정을 읽는다."""

import os
from urllib.parse import urlsplit


def get_allowed_origins() -> set[str]:
    """AUTH_ALLOWED_ORIGINS에 등록한 프론트 출처만 허용한다."""
    origins = {
        value.strip()
        for value in os.environ.get("AUTH_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    error_message = "AUTH_ALLOWED_ORIGINS에는 경로 없는 http/https 프론트 주소가 필요합니다."
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


def get_cookie_secure() -> bool:
    """기본은 HTTPS 쿠키이며 로컬 HTTP 개발에서만 false를 허용한다."""
    setting_value = os.environ.get("AUTH_COOKIE_SECURE", "true").strip().lower()
    if setting_value not in {"true", "false"}:
        raise RuntimeError("AUTH_COOKIE_SECURE는 true 또는 false여야 합니다.")
    return setting_value == "true"


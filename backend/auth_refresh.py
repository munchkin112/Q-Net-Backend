"""우리 서비스의 로그인 유지용 리프레시 토큰을 생성하고 해시로 변환한다."""

import hashlib
import re
import secrets


REFRESH_TOKEN_RANDOM_BYTES = 32
REFRESH_TOKEN_LENGTH = 43
REFRESH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def create_refresh_token() -> str:
    """32바이트 난수로 URL·쿠키에 사용할 수 있는 리프레시 토큰을 생성한다."""
    return secrets.token_urlsafe(REFRESH_TOKEN_RANDOM_BYTES)


def validate_refresh_token(token: str) -> None:
    """우리 서비스에서 발급한 토큰의 형식을 검사한다. 로그인 유효성은 별도로 확인한다."""
    if (
        not isinstance(token, str)
        or len(token) != REFRESH_TOKEN_LENGTH
        or REFRESH_TOKEN_PATTERN.fullmatch(token) is None
    ):
        raise ValueError("리프레시 토큰이 유효하지 않습니다.")


def create_refresh_token_hash(token: str) -> str:
    """토큰 형식을 확인하고 DB 저장·조회에 사용할 SHA-256 해시를 반환한다."""
    validate_refresh_token(token)
    return hashlib.sha256(token.encode("ascii")).hexdigest()
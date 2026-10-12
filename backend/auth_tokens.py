"""우리 서비스의 Bearer 액세스 토큰을 발급·검증한다. Google 토큰과는 별개다."""

from datetime import datetime, timezone
from uuid import UUID

import jwt
from pydantic import BaseModel, Field


ACCESS_TOKEN_TTL_SECONDS = 1800
ACCESS_TOKEN_ALGORITHM = "HS256"
ACCESS_TOKEN_ISSUER = "qnet-backend"
ACCESS_TOKEN_AUDIENCE = "qnet-api"
MIN_ACCESS_TOKEN_SECRET_LENGTH = 32
MAX_ACCESS_TOKEN_LENGTH = 4096


class AccessTokenExpiredError(ValueError):
    """서명은 유효하지만 사용 시간이 만료된 액세스 토큰이다."""


class AccessTokenClaims(BaseModel):
    """검증한 토큰에서 얻은 회원 ID와 로그인 세션 정보다."""

    user_id: UUID = Field(repr=False)
    session_id: UUID = Field(repr=False)
    issued_at: int = Field(ge=0, strict=True)
    expires_at: int = Field(gt=0, strict=True)


def validate_access_token_secret(secret_key: str) -> None:
    """전용 서명 키의 기본 형식을 검사한다. 실제 키는 충분히 무작위로 생성해야 한다."""
    if (
        not isinstance(secret_key, str)
        or not secret_key.isascii()
        or len(secret_key) < MIN_ACCESS_TOKEN_SECRET_LENGTH
        or secret_key != secret_key.strip()
    ):
        raise RuntimeError(
            "서비스 토큰에는 최소 32자의 별도 무작위 서명 키가 필요합니다."
        )


def create_access_token(
    user_id: UUID,
    session_id: UUID,
    *,
    secret_key: str,
) -> str:
    """서버에서 확인한 회원과 저장한 로그인 세션에 대해 30분짜리 토큰을 생성한다."""
    validate_access_token_secret(secret_key)

    if not isinstance(user_id, UUID) or not isinstance(session_id, UUID):
        raise ValueError(
            "로그인 토큰을 생성할 회원·세션 ID가 유효하지 않습니다."
        )

    issued_at = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iss": ACCESS_TOKEN_ISSUER,
        "aud": ACCESS_TOKEN_AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_TTL_SECONDS,
        "token_use": "access",
    }

    return jwt.encode(
        payload,
        secret_key,
        algorithm=ACCESS_TOKEN_ALGORITHM,
    )


def validate_access_token(
    token: str,
    *,
    secret_key: str,
) -> AccessTokenClaims:
    """서명·대상·발급자·만료를 검증한다. 세션 폐기 여부는 별도로 조회해야 한다."""
    validate_access_token_secret(secret_key)
    error_message = "로그인 토큰이 유효하지 않습니다."

    if (
        not isinstance(token, str)
        or not token
        or len(token) > MAX_ACCESS_TOKEN_LENGTH
    ):
        raise ValueError(error_message)

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            issuer=ACCESS_TOKEN_ISSUER,
            audience=ACCESS_TOKEN_AUDIENCE,
            options={
                "require": [
                    "sub", "sid", "iss", "aud",
                    "iat", "exp", "token_use",
                ],
                "strict_aud": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise AccessTokenExpiredError(
            "로그인 토큰의 사용 시간이 만료되었습니다."
        ) from None
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError):
        raise ValueError(error_message) from None

    if payload["token_use"] != "access":
        raise ValueError(error_message)

    try:
        claims = AccessTokenClaims(
            user_id=payload["sub"],
            session_id=payload["sid"],
            issued_at=payload["iat"],
            expires_at=payload["exp"],
        )
    except ValueError:
        raise ValueError(error_message) from None

    lifetime = claims.expires_at - claims.issued_at
    if not 0 < lifetime <= ACCESS_TOKEN_TTL_SECONDS:
        raise ValueError(error_message)

    return claims
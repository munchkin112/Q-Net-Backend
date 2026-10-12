"""FastAPI 보호 API에서 Bearer 토큰과 로그인 세션 검사를 재사용한다."""

from uuid import uuid4

import psycopg
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth_schemas import AuthUserResponse
from backend.auth_token_settings import get_auth_token_settings
from backend.auth_tokens import AccessTokenExpiredError
from backend.auth_user_service import (
    AuthSessionInvalidError,
    AuthUserInvalidError,
    get_authenticated_user,
)


auth_bearer = HTTPBearer(
    scheme_name="ServiceBearer",
    description="우리 서비스에서 발급한 액세스 토큰을 입력합니다.",
    auto_error=False,
)


class AuthRequestError(HTTPException):
    """인증 실패를 HTTP 상태와 오류 코드로 전달한다."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        headers = {"Cache-Control": "no-store"}

        if status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"

        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message},
            headers=headers,
        )


async def handle_auth_request_error(
    request: Request,
    error: AuthRequestError,
) -> JSONResponse:
    """인증 오류를 프로젝트의 공통 JSON 형식으로 반환한다."""
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.detail["code"],
                "message": error.detail["message"],
                "fields": [],
                "retryable": error.status_code >= 500,
            },
            "request_id": str(uuid4()),
        },
        headers=error.headers,
    )


def get_current_user(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_bearer),
) -> AuthUserResponse:
    """Bearer 토큰을 검사하고 해당 요청의 인증된 사용자를 반환한다."""
    if credentials is None:
        raise AuthRequestError(
            401,
            "AUTHENTICATION_REQUIRED",
            "로그인이 필요합니다.",
        )

    try:
        token_settings = get_auth_token_settings()

        user = get_authenticated_user(
            credentials.credentials,
            secret_key=token_settings.access_token_secret,
        )
    except AccessTokenExpiredError:
        raise AuthRequestError(
            401,
            "ACCESS_TOKEN_EXPIRED",
            "액세스 토큰의 사용 시간이 만료되었습니다.",
        ) from None
    except AuthSessionInvalidError:
        raise AuthRequestError(
            401,
            "SESSION_INVALID",
            "로그인 세션이 유효하지 않습니다. 다시 로그인해주세요.",
        ) from None
    except AuthUserInvalidError:
        raise AuthRequestError(
            401,
            "ACCESS_TOKEN_INVALID",
            "로그인 토큰이 유효하지 않습니다. 다시 로그인해주세요.",
        ) from None
    except (RuntimeError, psycopg.Error):
        raise AuthRequestError(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "사용자 인증을 처리할 수 없습니다. 잠시 후 다시 시도해주세요.",
        ) from None

    response.headers["Cache-Control"] = "no-store"

    return user
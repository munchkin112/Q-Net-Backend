"""Google 로그인 API의 입력과 응답 형식을 정의한다."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas import InputModel


class GoogleLoginRequest(InputModel):
    """프론트 콜백 화면에서 전달하는 인증 코드와 state다."""

    code: str = Field(min_length=1, repr=False)
    state: str = Field(min_length=1, repr=False)


class GoogleAuthorizeResponse(BaseModel):
    """브라우저를 이동시킬 Google 인증 주소다."""

    authorization_url: str


class AuthUserResponse(BaseModel):
    """외부에 반환할 최소 사용자 정보다."""

    id: UUID
    email: str | None


class CurrentUserResponse(BaseModel):
    """현재 사용자와 프로필 및 Calendar 연결 상태다."""

    user: AuthUserResponse
    profile_completed: bool
    calendar_connected: bool


class GoogleLoginResponse(CurrentUserResponse):
    """로그인 성공 시 반환하는 우리 서비스의 인증 정보다."""

    access_token: str = Field(min_length=1, repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)


class TokenRefreshResponse(BaseModel):
    """우리 서비스의 액세스 토큰 갱신 결과다."""

    access_token: str = Field(min_length=1, repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)
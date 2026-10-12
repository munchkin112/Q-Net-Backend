"""main.py에 등록하지 않은 프로필 조회·저장·마이페이지 수정 라우터다."""
from collections.abc import Callable

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from backend.api_identity import require_configured_user, get_authenticated_user_id
from backend.db.profile_repository import ProfileVersionConflict, ProfileUserNotFound
from backend.profile_form import ProfileFormPatch
from backend.profile_service import get_saved_profile, update_saved_profile, list_interest_categories


class ProfileResponse(BaseModel):
    """불완전한 기존 입력도 필요한 항목을 안내할 수 있도록 반환한다."""
    profile: dict | None
    profile_completed: bool
    missing_fields: list[str]
    profile_version: int = Field(ge=0)


class InterestCategoryResponse(BaseModel):
    code: str = Field(pattern=r'^(0[1-9]|1[0-9]|2[0-4])$')
    name: str


def create_profile_router(current_user_dependency: Callable = require_configured_user,
                          read_profile: Callable = get_saved_profile,
                          save_profile: Callable = update_saved_profile,
                          read_interests: Callable = list_interest_categories) -> APIRouter:
    """검증된 AuthUserResponse.id를 공유해 본인 정보만 처리한다."""
    router = APIRouter(tags=['관심 분야·프로필'])

    @router.get('/interest-categories', response_model=list[InterestCategoryResponse])
    def get_interest_categories(current_user=Depends(current_user_dependency)) -> list[dict]:
        """서비스 관심 분야 선택지 24개를 조회한다."""
        get_authenticated_user_id(current_user)
        try:
            return read_interests()
        except (psycopg.Error, RuntimeError):
            raise HTTPException(503, detail={'code': 'DATA_UNAVAILABLE', 'message': '관심 분야를 조회할 수 없습니다.'}) from None

    @router.get('/me/profile', response_model=ProfileResponse)
    def get_profile(current_user=Depends(current_user_dependency)) -> dict:
        """미입력도 200으로 반환하고 필요한 입력 항목을 안내한다."""
        user_id = get_authenticated_user_id(current_user)
        try:
            return read_profile(user_id)
        except (psycopg.Error, RuntimeError):
            raise HTTPException(503, detail={'code': 'PROFILE_UNAVAILABLE', 'message': '프로필을 조회할 수 없습니다.'}) from None

    @router.patch('/me/profile', response_model=ProfileResponse)
    def update_profile(request: ProfileFormPatch, current_user=Depends(current_user_dependency)) -> dict:
        """최초 저장과 부분 수정을 공통 처리한다. 사용자 ID는 요청에서 받지 않는다."""
        user_id = get_authenticated_user_id(current_user)
        changes = request.model_dump(exclude_unset=True, exclude={'profile_version'})
        try:
            return save_profile(user_id, request.profile_version, changes)
        except ProfileVersionConflict:
            raise HTTPException(409, detail={'code': 'PROFILE_CHANGED', 'message': '최신 프로필을 다시 조회해주세요.'}) from None
        except ProfileUserNotFound:
            raise HTTPException(401, detail={'code': 'SESSION_INVALID', 'message': '사용자 인증을 다시 확인해주세요.'}) from None
        except ValidationError as error:
            raise HTTPException(422, detail={'code': 'PROFILE_INCOMPLETE', 'message': '필수 입력과 경력 년차를 확인해주세요.',
                                'fields': list(dict.fromkeys(str(item['loc'][0]) for item in error.errors() if item['loc']))}) from None
        except (psycopg.Error, RuntimeError):
            raise HTTPException(503, detail={'code': 'PROFILE_UNAVAILABLE', 'message': '프로필을 저장할 수 없습니다.'}) from None

    return router


router = create_profile_router()

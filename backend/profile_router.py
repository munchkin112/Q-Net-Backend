"""로그인 없이 공개하는 서비스 관심 분야 목록 API다."""
from collections.abc import Callable

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.profile_service import list_interest_categories


class InterestCategoryResponse(BaseModel):
    """추천 요청에서 사용할 분야 코드와 한글 이름이다."""

    code: str = Field(pattern=r'^(0[1-9]|1[0-9]|2[0-4])$')
    name: str


def create_profile_router(
    read_interests: Callable = list_interest_categories,
) -> APIRouter:
    """DB에 저장하지 않는 프로필 방식에 맞춰 관심 분야 목록만 제공한다."""
    router = APIRouter(tags=['관심 분야·프로필'])

    @router.get('/interest-categories', response_model=list[InterestCategoryResponse])
    def get_interest_categories() -> list[dict]:
        """서비스 관심 분야 선택지 24개를 조회한다."""
        try:
            return read_interests()
        except (psycopg.Error, RuntimeError):
            raise HTTPException(
                503,
                detail={'code': 'DATA_UNAVAILABLE', 'message': '관심 분야를 조회할 수 없습니다.'},
            ) from None

    return router


router = create_profile_router()


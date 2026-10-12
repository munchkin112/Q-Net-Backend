"""추천 카드와 상세 화면 직무 안내의 HTTP 응답 계약이다."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from backend.profile_form import ProfileForm


class RecommendationRequest(ProfileForm):
    """로그인 없이 프론트가 보낸 프로필 입력으로 추천을 실행한다."""


class CareerInformationResponse(BaseModel):
    certificate_id: UUID
    status: Literal['available', 'unavailable']
    recommended_for: list[dict] = Field(max_length=3)
    related_jobs: list[dict]
    sources: list[dict]
    usage_restrictions: list
    message: str


class RecommendationCard(BaseModel):
    certificate_id: UUID
    qnet_code: str
    name: str
    category: str
    category_name: str
    summary: str
    position: int = Field(ge=1, le=10)
    reason: str
    profile_factors: list[str]
    evidence: list[dict]
    recommended_for: list[dict] = Field(max_length=3)
    related_jobs: list[dict]
    related_jobs_status: Literal['available', 'unavailable']
    sources: list[dict]
    usage_restrictions: list


class RecommendationResponse(BaseModel):
    status: Literal['completed', 'no_results']
    ordering: Literal['llm_relevance'] = 'llm_relevance'
    selection_scope: Literal['searched_candidates_only'] = 'searched_candidates_only'
    total_count: int = Field(ge=0, le=10)
    initial_display_count: int = Field(ge=0, le=3)
    items: list[RecommendationCard] = Field(max_length=10)


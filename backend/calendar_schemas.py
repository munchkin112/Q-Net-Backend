"""사용자 선택 Calendar 등록 API의 요청·응답을 정의한다."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from backend.schemas import InputModel


CalendarEventType = Literal["registration", "written_exam", "practical_exam", "result"]
CalendarItemStatus = Literal["created", "already_registered", "failed", "unknown"]
CalendarRegistrationStatus = Literal[
    "completed", "partial", "failed", "pending_confirmation"
]


class CalendarRegisterRequest(InputModel):
    """화면에서 선택한 회차와 등록 항목만 서버에 전달한다."""

    certificate_id: UUID
    schedule_ids: list[UUID] = Field(
        min_length=1,
        max_length=6,
        description="선택 회차의 필기·실기 등 일정 ID 목록",
    )
    schedule_versions: dict[UUID, datetime] = Field(
        description="GET 일정 응답에서 받은 각 일정의 updated_at",
    )
    event_types: list[CalendarEventType] = Field(
        min_length=1,
        max_length=4,
        description="화면에서 사용자가 선택한 원서접수·필기·실기·합격발표 항목만 전달",
    )

    @model_validator(mode="after")
    def validate_selection(self):
        """회차·일정 버전·이벤트 종류가 중복 없이 정확히 연결됐는지 확인한다."""
        if len(set(self.schedule_ids)) != len(self.schedule_ids):
            raise ValueError("시험 일정은 중복 선택할 수 없습니다.")
        if len(set(self.event_types)) != len(self.event_types):
            raise ValueError("Calendar 등록 항목은 중복 선택할 수 없습니다.")
        if set(self.schedule_versions) != set(self.schedule_ids):
            raise ValueError("각 시험 일정의 조회 버전이 필요합니다.")
        if any(version.utcoffset() is None for version in self.schedule_versions.values()):
            raise ValueError("시험 일정 조회 시각에는 시간대가 필요합니다.")
        return self


class CalendarItemResponse(BaseModel):
    """요청한 이벤트 한 건의 실제 처리 결과다."""

    item_key: str
    event_type: CalendarEventType
    status: CalendarItemStatus
    google_event_id: str | None = None
    html_link: str | None = None
    code: str | None = None
    message: str | None = None
    retryable: bool = False


class CalendarExcludedItemResponse(BaseModel):
    """선택했지만 공식 일정이 부족해 만들지 못한 항목이다."""

    event_type: CalendarEventType
    reason: str
    schedule_id: UUID | None = None
    period_index: int | None = Field(default=None, ge=1)


class CalendarRegisterResponse(BaseModel):
    """선택 항목별 Google Calendar 처리 결과를 반환한다."""

    registration_id: UUID
    status: CalendarRegistrationStatus
    items: list[CalendarItemResponse]
    excluded_items: list[CalendarExcludedItemResponse]
    message: str


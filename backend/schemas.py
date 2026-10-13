"""사용자 프로필과 시험 단계별 공식 일정의 입력값을 검증한다."""

from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CertificateInput(InputModel):
    """공식 종목 목록에서 확인한 저장 입력값이다."""

    qnet_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https?://")
    last_synced_at: datetime

    @model_validator(mode="after")
    def validate_retrieved_at(self) -> Self:
        """공식 조회 시각에 시간대가 포함되어 있는지 확인한다."""
        if self.last_synced_at.utcoffset() is None:
            raise ValueError("조회 시각에는 시간대가 필요합니다.")
        return self


class CareerEntry(InputModel):
    job_title: str = Field(min_length=1)
    field_code: str | None = None
    started_on: date | None = None
    ended_on: date | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.started_on and self.ended_on and self.started_on > self.ended_on:
            raise ValueError("경력 시작일은 종료일보다 늦을 수 없습니다.")
        return self


class QualificationEntry(InputModel):
    name: str = Field(min_length=1)
    qnet_code: str | None = None
    acquired_on: date | None = None
    # Self-reported inputs are not institution-verified evidence.
    verification_status: Literal["self_reported"] = "self_reported"


class ProfilePatch(InputModel):
    education_level: str | None = Field(default=None, min_length=1)
    education_status: Literal["graduated", "enrolled", "expected", "other"] | None = None
    graduation_date: date | None = None
    major: str | None = Field(default=None, min_length=1)
    major_status: Literal["provided", "not_applicable", "unknown"] | None = None
    has_career: bool | None = None
    career_history: list[CareerEntry] | None = None
    qualifications: list[QualificationEntry] | None = None
    desired_job: str | None = Field(default=None, min_length=1)
    current_status: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, min_length=1)
    target_date: date | None = None


def validate_profile_state(profile: dict) -> None:
    """부분 수정 요청에서 생략한 기존 값까지 포함해 병합된 프로필을 검증한다."""
    if profile.get("has_career") is False and profile.get("career_history"):
        raise ValueError("경력 없음과 경력 내역을 동시에 저장할 수 없습니다.")
    if profile.get("major_status") == "provided" and not profile.get("major"):
        raise ValueError("전공 입력 상태에는 전공명이 필요합니다.")
    if profile.get("major_status") in {"not_applicable", "unknown"} and profile.get("major"):
        raise ValueError("전공명과 전공 상태를 함께 확인해주세요.")


class RegistrationPeriod(InputModel):
    """실제로 접수를 받는 한 기간을 보관한다."""

    starts_on: date
    ends_on: date
    source_url: str | None = Field(default=None, pattern=r'^https?://')
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """접수기간 시작일이 종료일보다 늦으면 거절한다."""
        if self.starts_on > self.ends_on:
            raise ValueError('접수기간 시작일은 종료일보다 늦을 수 없습니다.')
        if (self.source_url is None) != (self.retrieved_at is None):
            raise ValueError('접수기간의 출처와 조회 시각은 함께 제공해야 합니다.')
        if self.retrieved_at is not None and self.retrieved_at.utcoffset() is None:
            raise ValueError('접수기간 조회 시각에는 시간대가 필요합니다.')
        return self


class ScheduleInput(InputModel):
    certificate_id: UUID
    year: int = Field(ge=1900, le=9999)
    round_key: str = Field(min_length=1)
    round_label: str = Field(min_length=1)
    phase: Literal["written", "practical", "interview", "first", "second", "other"]
    registration_start: date | None = None
    registration_end: date | None = None
    registration_periods: list[RegistrationPeriod] = Field(
        default_factory=list, description='실제 접수기간 목록. 접수가 나뉘면 이 목록을 사용합니다. 시작·종료 필드는 전체 범위입니다.',
    )
    exam_start: date | None = None
    exam_end: date | None = None
    result_date: date | None = None
    result_display_end: date | None = None
    vacancy_registration_start: date | None = None
    vacancy_registration_end: date | None = None
    exam_site: str | None = None
    source_url: str = Field(pattern=r"^https?://", min_length=1)
    last_synced_at: datetime

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        """기간 목록과 접수·시험·발표의 날짜 순서를 검증한다."""
        if self.registration_periods:
            if self.registration_start != self.registration_periods[0].starts_on or self.registration_end != self.registration_periods[-1].ends_on:
                raise ValueError('접수기간 목록과 전체 시작·종료 범위가 일치해야 합니다.')
            for previous, current in zip(self.registration_periods, self.registration_periods[1:]):
                if previous.ends_on >= current.starts_on:
                    raise ValueError('접수기간 목록은 날짜순이어야 하며 서로 겹칠 수 없습니다.')
        pairs = [
            ("registration_start", "registration_end"),
            ("registration_end", "exam_start"),
            ("exam_start", "exam_end"),
            ("exam_end", "result_date"),
            ("result_date", "result_display_end"),
            ("vacancy_registration_start", "vacancy_registration_end"),
            ("vacancy_registration_end", "exam_start"),
        ]
        for earlier, later in pairs:
            earlier_date, later_date = getattr(self, earlier), getattr(self, later)
            if earlier_date and later_date and earlier_date > later_date:
                raise ValueError(f"날짜 순서 오류: {earlier} > {later}")
        # A missing period boundary must not hide a contradiction in known dates.
        exam_first = self.exam_start or self.exam_end
        exam_last = self.exam_end or self.exam_start
        registration_last = self.registration_end or self.registration_start
        vacancy_last = self.vacancy_registration_end or self.vacancy_registration_start
        for earlier_date, later_date in (
            (registration_last, exam_first),
            (vacancy_last, exam_first),
            (exam_last, self.result_date),
        ):
            if earlier_date and later_date and earlier_date > later_date:
                raise ValueError("확인된 접수·시험·발표 날짜의 순서가 맞지 않습니다.")
        if self.last_synced_at.utcoffset() is None:
            raise ValueError("조회 시각에는 시간대가 필요합니다.")
        return self

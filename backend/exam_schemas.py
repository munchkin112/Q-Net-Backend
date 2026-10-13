"""시험과목·합격기준·응시료와 각 정보의 공식 출처를 정의한다."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.schemas import InputModel


class SourceInfo(InputModel):
    """정보를 확인한 원본 주소와 시각을 보관한다."""

    status: Literal["available", "partial", "unavailable"] = "unavailable"
    source_url: str | None = Field(default=None, pattern=r"^https?://")
    retrieved_at: datetime | None = None
    phases: list[Literal["written", "practical", "interview"]] = Field(
        default_factory=lambda: ["written", "practical"],
        description="공식 자료에서 확인한 시험 단계. 필기·실기, 필기·면접, 실기 단독을 구분합니다.",
    )

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """출처 주소와 시각을 함께 보관하고 시간대 없는 시각을 거절한다."""
        if (self.source_url is None) != (self.retrieved_at is None):
            raise ValueError("공식 출처와 조회 시각은 함께 입력해야 합니다.")
        if self.retrieved_at is not None and self.retrieved_at.utcoffset() is None:
            raise ValueError("조회 시각에는 시간대가 필요합니다.")
        if self.phases not in (["written", "practical"], ["written", "interview"], ["practical"]):
            raise ValueError("지원하지 않는 시험 단계 구성입니다.")
        return self


class SubjectsInfo(SourceInfo):
    """확인되지 않은 과목은 빈 목록 대신 null로 표시한다."""

    written: list[Annotated[str, Field(min_length=1)]] | None = Field(default=None, min_length=1)
    practical: list[Annotated[str, Field(min_length=1)]] | None = Field(default=None, min_length=1)
    interview: list[Annotated[str, Field(min_length=1)]] | None = Field(default=None, min_length=1)
    common: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None, min_length=1, description="원문에 단계 구분 없이 제공된 과목. 특정 단계로 추정하지 않습니다.",
    )


class PassCriteriaInfo(SourceInfo):
    """점수 기준을 임의로 해석하지 않고 공식 문장으로 보관한다."""

    written: str | None = Field(default=None, min_length=1)
    practical: str | None = Field(default=None, min_length=1)
    interview: str | None = Field(default=None, min_length=1)
    common: str | None = Field(default=None, min_length=1, description="원문에 단계 구분 없이 제공된 합격기준")


class FeesInfo(SourceInfo):
    """응시료는 원 단위 정수로 보관하며 미확인은 null로 구분한다."""

    written: int | None = Field(default=None, ge=0, strict=True)
    practical: int | None = Field(default=None, ge=0, strict=True)
    interview: int | None = Field(default=None, ge=0, strict=True)
    currency: Literal["KRW"] = "KRW"


def information_status(written: object, practical: object, interview: object = None,
                       common: object = None, phases: list[str] | None = None) -> str:
    """해당 종목의 시험 단계를 모두 확인했는지 판단한다. 금액 0도 확인된 값이다."""
    if common is not None:
        return "available"
    values = {"written": written, "practical": practical, "interview": interview}
    required = phases if phases is not None else ["written", "practical"]
    if all(values[phase] is not None for phase in required):
        return "available"
    if any(values[phase] is not None for phase in required):
        return "partial"
    return "unavailable"


class ExamInformationInput(InputModel):
    """공식 자료를 검증한 후 DB 저장 함수에 전달하는 입력값이다."""

    certificate_id: UUID
    subjects: SubjectsInfo
    pass_criteria: PassCriteriaInfo
    fees: FeesInfo
    raw_acquisition_text: str | None = None
    raw_fee_text: str | None = None

    @model_validator(mode="after")
    def validate_information(self) -> Self:
        """표시 상태가 실제 값과 일치하고 확인된 정보에 출처가 있는지 검사한다."""
        for info in (self.subjects, self.pass_criteria, self.fees):
            expected = information_status(info.written, info.practical, info.interview,
                                          getattr(info, "common", None), info.phases)
            if info.status != expected:
                raise ValueError("시험정보 상태와 실제 값이 일치하지 않습니다.")
            if expected != "unavailable" and info.source_url is None:
                raise ValueError("확인한 시험정보에는 공식 출처가 필요합니다.")
            if info.phases != self.subjects.phases:
                raise ValueError("과목·기준·응시료의 시험 단계가 일치해야 합니다.")
            if info.practical is not None and "practical" not in info.phases:
                raise ValueError("면접 시험의 값을 실기로 저장할 수 없습니다.")
            if info.written is not None and "written" not in info.phases:
                raise ValueError("실기만 시행하는 종목에 필기 정보를 저장할 수 없습니다.")
            if info.interview is not None and "interview" not in info.phases:
                raise ValueError("면접이 확인되지 않은 종목에 면접 정보를 저장할 수 없습니다.")
        return self

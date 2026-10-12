"""로그인 없이 추천 요청으로 받은 프로필 입력을 검증한다."""
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProfileForm(BaseModel):
    """관심 분야 한 개, 학력·졸업 상태·경력과 선택 전공을 검증한다."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    interest_category_codes: list[str] = Field(min_length=1, max_length=1)
    education_level: Literal['high_school_or_below', 'college', 'university', 'graduate_school', 'other']
    education_status: Literal['graduated', 'enrolled', 'expected', 'other']
    major: str | None = Field(default=None, max_length=200)
    has_career: bool = Field(strict=True)
    career_years: float | None = Field(default=None, ge=0, le=80, allow_inf_nan=False)

    @field_validator('interest_category_codes')
    @classmethod
    def validate_interest_codes(cls, codes: list[str]) -> list[str]:
        """서비스 관심 코드 01~24 중 한 개를 허용한다."""
        if codes[0] not in [f'{number:02}' for number in range(1, 25)]:
            raise ValueError('관심 분야는 01~24 중 선택해주세요.')
        return codes

    @field_validator('career_years', mode='before')
    @classmethod
    def validate_year_number(cls, value: object) -> object:
        """참·거짓과 문자열을 숫자로 잘못 해석하지 않는다."""
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError('경력 년차는 숫자로 입력해주세요.')
        return value

    @field_validator('major')
    @classmethod
    def normalize_major(cls, value: str | None) -> str | None:
        """빈 선택 입력을 null로 정리한다."""
        return value or None

    @model_validator(mode='after')
    def validate_career(self) -> Self:
        """경력 있을 때 년차를 필수로 받고 없을 때는 비운다."""
        if self.has_career and self.career_years is None:
            raise ValueError('관련 직무 년차를 입력해주세요.')
        if not self.has_career and self.career_years is not None:
            raise ValueError('경력 없음이면 년차를 비워주세요.')
        return self


class ProfileFormPatch(BaseModel):
    """레거시 서버 프로필 수정 형식이다. 현재 API에는 연결하지 않는다."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    profile_version: int = Field(ge=0, strict=True)
    interest_category_codes: list[str] | None = Field(default=None, min_length=1, max_length=1)
    education_level: Literal['high_school_or_below', 'college', 'university', 'graduate_school', 'other'] | None = None
    education_status: Literal['graduated', 'enrolled', 'expected', 'other'] | None = None
    major: str | None = Field(default=None, max_length=200)
    has_career: bool | None = Field(default=None, strict=True)
    career_years: float | None = Field(default=None, ge=0, le=80, strict=True, allow_inf_nan=False)


def merge_profile_form(current: dict | None, changes: dict) -> dict:
    """레거시 프로필 저장 코드에서 기존 값과 변경값을 병합한다."""
    values = {**(current or {}), **changes}
    if changes.get('has_career') is False and 'career_years' not in changes:
        values['career_years'] = None
    return ProfileForm.model_validate(values).model_dump()


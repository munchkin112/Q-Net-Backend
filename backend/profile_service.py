"""프로필 저장·조회 연결과 입력 완료 상태를 구성한다."""
from uuid import UUID

from pydantic import ValidationError

from backend.db.connection import database_connection
from backend.db.profile_repository import get_profile_form, update_profile_form, get_form_values
from backend.db.recommendation_repository import list_recommendation_interests
from backend.profile_form import ProfileForm, merge_profile_form


def build_profile_response(row: dict | None) -> dict:
    """미입력과 과거 불완전 입력을 구분하며 실제 저장 값만 보여준다."""
    values = get_form_values(row)
    try:
        profile = ProfileForm.model_validate(values or {}).model_dump()
        missing = []
    except ValidationError as error:
        profile = values
        missing = list(dict.fromkeys(str(item['loc'][0]) for item in error.errors() if item['loc']))
    return {'profile': profile, 'profile_completed': not missing, 'missing_fields': missing,
            'profile_version': row['profile_version'] if row else 0}


def get_saved_profile(user_id: UUID) -> dict:
    """로그인한 사용자의 입력값과 수정 버전을 조회한다."""
    with database_connection() as connection:
        return build_profile_response(get_profile_form(connection, user_id))


def update_saved_profile(user_id: UUID, expected_version: int, changes: dict) -> dict:
    """트랜잭션 안에서 검증·저장하고 저장된 값으로 응답한다."""
    with database_connection() as connection:
        row = update_profile_form(connection, user_id, expected_version, changes)
    return build_profile_response(row)


def load_saved_profile_form(user_id: UUID) -> dict:
    """추천 API가 사용할 저장 프로필만 반환한다. 미입력은 빈 객체로 필수 검증에 전달한다."""
    response = get_saved_profile(user_id)
    return response['profile'] or {}


def list_interest_categories() -> list[dict]:
    """공식 분류 판정이 아닌 서비스 선택지의 코드·이름을 반환한다."""
    with database_connection() as connection:
        choices = list_recommendation_interests(connection)
    return [{'code': choice['code'], 'name': choice['name']} for choice in choices]

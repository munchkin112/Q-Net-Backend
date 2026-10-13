"""사용자 UUID로 프로필 화면 입력을 저장·조회한다."""
from uuid import UUID

from psycopg import Connection

from backend.profile_form import merge_profile_form


class ProfileVersionConflict(ValueError):
    """다른 요청이 먼저 저장한 프로필을 덮어쓰지 않는다."""


class ProfileUserNotFound(ValueError):
    """인증 사용자와 DB 사용자 존재가 일치하지 않는다."""


def get_form_values(row: dict | None) -> dict | None:
    """DB 메타데이터를 제거하고 단일 관심 코드·숫자 년차를 화면 계약으로 변환한다."""
    if row is None:
        return None
    return {'interest_category_codes': [row['interest_category_code']] if row['interest_category_code'] else [],
            'education_level': row['education_level'], 'education_status': row['education_status'],
            'major': row['major'], 'has_career': row['has_career'],
            'career_years': float(row['career_years']) if row['career_years'] is not None else None}


def get_profile_form(connection: Connection, user_id: UUID) -> dict | None:
    """인증된 본인의 저장 값만 조회한다. 테이블 미적용은 DB 오류로 구분한다."""
    return connection.execute('''SELECT interest_category_code,education_level,education_status,
        major,has_career,career_years,profile_version FROM user_profiles WHERE user_id=%s''', (user_id,)).fetchone()


def update_profile_form(connection: Connection, user_id: UUID, expected_version: int, changes: dict) -> dict:
    """사용자별 잠금과 수정 버전으로 동시 저장을 보호하고 검증된 필드만 갱신한다."""
    with connection.transaction():
        # 최초 프로필이 없을 때도 같은 사용자에 대한 동시 요청을 순서대로 처리한다.
        user = connection.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
        if user is None:
            raise ProfileUserNotFound()
        row = get_profile_form(connection, user_id)
        version = row['profile_version'] if row else 0
        if expected_version != version:
            raise ProfileVersionConflict()
        current = get_form_values(row)
        values = merge_profile_form(current, changes)
        if row and values == current:
            return row
        return connection.execute('''INSERT INTO user_profiles
            (user_id,interest_category_code,education_level,education_status,major,major_status,
             has_career,career_years,profile_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET
                interest_category_code=EXCLUDED.interest_category_code,
                education_level=EXCLUDED.education_level,education_status=EXCLUDED.education_status,
                major=EXCLUDED.major,major_status=EXCLUDED.major_status,
                has_career=EXCLUDED.has_career,career_years=EXCLUDED.career_years,
                career_history=CASE WHEN EXCLUDED.has_career=false THEN '[]'::jsonb ELSE user_profiles.career_history END,
                profile_version=EXCLUDED.profile_version,updated_at=now()
            RETURNING interest_category_code,education_level,education_status,major,has_career,career_years,profile_version''',
            (user_id, values['interest_category_codes'][0], values['education_level'], values['education_status'],
             values['major'], 'provided' if values['major'] else 'unknown', values['has_career'],
             values['career_years'], version + 1)).fetchone()

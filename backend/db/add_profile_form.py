"""실행할 때만 프로필 화면 필드 SQL을 적용한다. 서버 시작 시 실행하지 않는다."""
from pathlib import Path

import psycopg

from backend.db.connection import database_connection


def add_profile_form_fields() -> None:
    """관심 선택지 테이블의 존재를 확인하고 한 트랜잭션으로 필드를 추가한다."""
    schema = Path(__file__).with_name('profile_form.sql').read_text(encoding='utf-8')
    with database_connection() as connection:
        connection.execute(schema)


if __name__ == '__main__':
    try:
        add_profile_form_fields()
        print('프로필 입력 필드 적용 완료')
    except (psycopg.Error, RuntimeError):
        print('적용 실패: DB 설정과 추천 관심 선택지 테이블을 확인해주세요. 변경은 취소됩니다.')
        raise SystemExit(1) from None

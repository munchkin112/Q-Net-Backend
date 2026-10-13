"""명시적으로 실행할 때만 초기 테이블을 생성하며, 앱 시작 시 자동 실행하지 않는다."""

from pathlib import Path

import psycopg

from backend.db.connection import database_connection


def initialize_database() -> None:
    """새 데이터베이스에 확정된 테이블을 하나의 트랜잭션으로 생성한다."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    exam_schema = Path(__file__).with_name("exam_information.sql").read_text(encoding="utf-8")
    with database_connection() as connection:
        connection.execute(schema)
        connection.execute(exam_schema)


if __name__ == "__main__":
    try:
        initialize_database()
        print("확정 범위의 DB 테이블 생성 완료")
    except (psycopg.Error, RuntimeError, ValueError):
        print("테이블 생성 실패: DB 연결 설정과 기존 테이블 유무를 확인해주세요. 변경은 취소됩니다.")
        raise SystemExit(1) from None

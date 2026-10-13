"""기존 DB의 자료를 유지하면서 시험 상세정보 테이블만 추가한다."""

from pathlib import Path

import psycopg

from backend.db.connection import database_connection


def add_exam_information_table() -> bool:
    """테이블이 없을 때만 생성한다. 이미 있으면 기존 구조와 자료를 유지한다."""
    schema = Path(__file__).with_name("exam_information.sql").read_text(encoding="utf-8")
    with database_connection() as connection:
        existing = connection.execute("SELECT to_regclass('public.exam_information') AS relation").fetchone()
        if existing["relation"] is not None:
            return False
        connection.execute(schema)
    return True


if __name__ == "__main__":
    try:
        created = add_exam_information_table()
        print("시험 상세정보 테이블 생성 완료" if created else "기존 상세정보 테이블을 유지합니다.")
    except (psycopg.Error, RuntimeError, ValueError):
        print("상세정보 테이블 추가 실패: DB 연결과 기존 구조를 확인해주세요. 변경은 취소됩니다.")
        raise SystemExit(1) from None

"""DB 접속과 필수 테이블 존재 여부를 쓰기 작업 없이 검사한다."""

import json
import os

import psycopg

from backend.db.connection import database_connection


REQUIRED_TABLES = ("users", "user_profiles", "certificates", "schedules", "exam_information")


def check_database() -> dict:
    """설정 유무와 실제 접속을 구분하며 연결 URL이나 인증정보를 반환하지 않는다."""
    result = {
        "configured": bool(os.environ.get("DATABASE_URL")),
        "connected": False,
        "tables_ready": False,
        "missing_tables": [],
        "status": "not_configured",
    }
    if not result["configured"]:
        return result
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            result["connected"] = True
            for table in REQUIRED_TABLES:
                row = connection.execute(
                    "SELECT to_regclass(%s) AS relation", ("public." + table,)
                ).fetchone()
                if row["relation"] is None:
                    result["missing_tables"].append(table)
        result["tables_ready"] = not result["missing_tables"]
        result["status"] = "ready" if result["tables_ready"] else "tables_missing"
    except (psycopg.Error, RuntimeError, ValueError):
        result["status"] = "unavailable"
    return result


def main() -> None:
    """검사 결과를 표시하고 접속·테이블 준비가 안 됐다면 실패 상태로 종료한다."""
    result = check_database()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["tables_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

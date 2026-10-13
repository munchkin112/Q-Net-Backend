"""인증 기능에 필요한 DB 테이블을 변경 없이 확인한다."""

import json
import os

import psycopg

from backend.db.connection import database_connection


AUTH_REQUIRED_TABLES = ("users", "auth_sessions", "auth_refresh_tokens")


def check_auth_database() -> dict:
    """연결정보를 출력하지 않고 인증 테이블 준비 상태만 반환한다."""
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
            for table in AUTH_REQUIRED_TABLES:
                row = connection.execute(
                    "SELECT to_regclass(%s) AS relation",
                    ("public." + table,),
                ).fetchone()
                if row is None or row["relation"] is None:
                    result["missing_tables"].append(table)
        result["tables_ready"] = not result["missing_tables"]
        result["status"] = "ready" if result["tables_ready"] else "tables_missing"
    except (psycopg.Error, RuntimeError, ValueError):
        result["status"] = "unavailable"

    return result


def main() -> None:
    """설정·접속·테이블 상태를 표시하고 준비되지 않았으면 실패로 종료한다."""
    result = check_auth_database()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["tables_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

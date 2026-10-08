"""인증정보를 로그에 남기지 않고 Render PostgreSQL 연결 URL로 접속한다."""

import os
from contextlib import contextmanager
from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row

from backend import settings  # 서버와 실행 명령에서 동일한 로컬 설정을 읽는다.


@contextmanager
def database_connection() -> Iterator[psycopg.Connection]:
    """성공 시 변경을 확정하고 오류 시 취소하며, 작업 후 연결을 항상 닫는다."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 환경변수가 필요합니다.")
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as connection:
        yield connection

"""기존 일정의 ID·날짜를 유지하며 접수기간 목록과 면접 단계를 추가한다."""

from pathlib import Path

from backend.db.connection import database_connection


def main() -> None:
    """변경 SQL을 하나의 트랜잭션으로 적용한다."""
    source = Path(__file__).with_name('schedule_periods.sql').read_text(encoding='utf-8')
    with database_connection() as connection:
        connection.execute(source)
    print('일정 접수기간 목록·면접 단계 적용 완료')


if __name__ == '__main__':
    main()

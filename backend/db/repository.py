"""데이터 저장·조회 함수를 제공하며, 호출하는 쪽에서 트랜잭션과 사용자 신원을 관리한다."""

from uuid import UUID, uuid4
from datetime import datetime

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from backend.schemas import CertificateInput, ProfilePatch, ScheduleInput, validate_profile_state


def save_certificate(connection: Connection, certificate: CertificateInput) -> dict:
    """공식 코드로 종목을 저장·갱신하며 기존 ID와 팀이 입력한 태그를 유지한다."""
    saved = connection.execute(
        """INSERT INTO certificates (id, qnet_code, name, category, source_url, last_synced_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (qnet_code) DO UPDATE SET
            name = EXCLUDED.name, category = EXCLUDED.category,
            source_url = EXCLUDED.source_url, last_synced_at = EXCLUDED.last_synced_at,
            updated_at = now()
        WHERE EXCLUDED.last_synced_at >= certificates.last_synced_at
        RETURNING *""",
        (uuid4(), certificate.qnet_code, certificate.name, certificate.category,
         certificate.source_url, certificate.last_synced_at),
    ).fetchone()
    if saved is not None:
        return saved
    return connection.execute(
        "SELECT * FROM certificates WHERE qnet_code = %s", (certificate.qnet_code,)
    ).fetchone()


def search_certificates(
    connection: Connection, query: str = "", category: str | None = None,
    limit: int = 20, offset: int = 0,
) -> list[dict]:
    """종목명 부분 일치 또는 공식 코드로 검색하며 모든 입력값을 SQL 매개변수로 전달한다."""
    return connection.execute(
        """SELECT * FROM certificates
        WHERE (position(lower(%s) in lower(name)) > 0 OR qnet_code = %s)
          AND (%s::text IS NULL OR category = %s)
        ORDER BY name, qnet_code LIMIT %s OFFSET %s""",
        (query, query, category, category, limit, offset),
    ).fetchall()


def get_profile(connection: Connection, user_id: UUID) -> dict | None:
    """사용자 프로필을 조회한다. 향후 API에서는 서버에서 인증한 사용자 ID를 전달한다."""
    return connection.execute(
        "SELECT * FROM user_profiles WHERE user_id = %s", (user_id,)
    ).fetchone()


def save_profile(connection: Connection, user_id: UUID, patch: ProfilePatch) -> dict:
    """전달된 필드만 저장하며, 경력 날짜와 보유 자격은 선택 입력으로 유지한다."""
    with connection.transaction():
        connection.execute(
            "INSERT INTO user_profiles (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
            (user_id,),
        )
        current = connection.execute(
            "SELECT * FROM user_profiles WHERE user_id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        updates = patch.model_dump(exclude_unset=True, mode="python")
        # Null clears arrays to []; omitted arrays preserve the stored value.
        for name in ("career_history", "qualifications"):
            if name in updates:
                updates[name] = [entry.model_dump(mode="json") for entry in getattr(patch, name) or []]
        validate_profile_state({**current, **updates})
        if not updates:
            return current
        assignments = [sql.SQL("{} = %s").format(sql.Identifier(name)) for name in updates]
        values = [Jsonb(value) if name in {"career_history", "qualifications"} else value
                  for name, value in updates.items()]
        query = sql.SQL("UPDATE user_profiles SET {}, updated_at = now() WHERE user_id = %s RETURNING *").format(
            sql.SQL(", ").join(assignments)
        )
        return connection.execute(query, [*values, user_id]).fetchone()


def save_schedule(connection: Connection, schedule: ScheduleInput, preserve_known: bool = False) -> dict:
    """정규화된 한 시험 단계의 일정을 저장하거나 갱신하며, 기존 ID를 유지한다."""
    if preserve_known:
        existing = connection.execute(
            'SELECT * FROM schedules WHERE certificate_id = %s AND round_key = %s AND phase = %s FOR UPDATE',
            (schedule.certificate_id, schedule.round_key, schedule.phase),
        ).fetchone()
        if existing is not None:
            for name in ('registration_start', 'registration_end', 'exam_start', 'exam_end',
                         'result_date', 'result_display_end', 'vacancy_registration_start', 'vacancy_registration_end'):
                if existing[name] is not None and getattr(schedule, name) is None:
                    return enrich_registration_periods(connection, existing, schedule)
            if existing.get('registration_periods') and not schedule.registration_periods:
                return existing
    values = schedule.model_dump(mode="python")
    values['registration_periods'] = Jsonb(schedule.model_dump(mode='json')['registration_periods'])
    columns = list(values)
    mutable_columns = [name for name in columns if name not in {"certificate_id", "round_key", "phase"}]
    updates = [sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
               for name in mutable_columns]
    query = sql.SQL("""
        INSERT INTO schedules (id, {}) VALUES (%s, {})
        ON CONFLICT (certificate_id, round_key, phase)
        DO UPDATE SET {}, updated_at = now()
        WHERE EXCLUDED.last_synced_at >= schedules.last_synced_at
        RETURNING *
    """).format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        sql.SQL(", ").join(updates),
    )
    with connection.transaction():
        saved = connection.execute(query, [uuid4(), *values.values()]).fetchone()
        if saved is not None:
            return saved
        return connection.execute(
            "SELECT * FROM schedules WHERE certificate_id = %s AND round_key = %s AND phase = %s",
            (schedule.certificate_id, schedule.round_key, schedule.phase),
        ).fetchone()


def enrich_registration_periods(connection: Connection, existing: dict, schedule: ScheduleInput) -> dict:
    """기존 날짜·출처는 보존하고 같은 접수 범위의 상세 기간만 자체 출처와 함께 보완한다."""
    known_times = [datetime.fromisoformat(period['retrieved_at']) for period in existing.get('registration_periods', [])
                   if period.get('retrieved_at')]
    current_time = max([existing['last_synced_at'], *known_times])
    periods = schedule.model_dump(mode='json')['registration_periods']
    if (periods and all(period['source_url'] and period['retrieved_at'] for period in periods)
            and schedule.registration_start == existing['registration_start']
            and schedule.registration_end == existing['registration_end']
            and min(datetime.fromisoformat(period['retrieved_at']) for period in periods) >= current_time):
        return connection.execute(
            'UPDATE schedules SET registration_periods = %s, updated_at = now() WHERE id = %s RETURNING *',
            (Jsonb(periods), existing['id']),
        ).fetchone()
    return existing


def list_schedules(connection: Connection, certificate_id: UUID, year: int) -> list[dict]:
    """필기·실기 등 각 시험 단계의 일정을 별도 행으로 조회한다."""
    return connection.execute(
        "SELECT * FROM schedules WHERE certificate_id = %s AND year = %s ORDER BY round_key, phase",
        (certificate_id, year),
    ).fetchall()


# FUTURE BOOKMARK: uncomment this block after applying db/bookmarks.sql.
# def add_bookmark(connection: Connection, user_id: UUID, certificate_id: UUID) -> dict:
#     """중복 등록 요청이면 기존 북마크를 반환한다."""
#     return connection.execute(
#         """INSERT INTO bookmarks (id, user_id, certificate_id) VALUES (%s, %s, %s)
#         ON CONFLICT (user_id, certificate_id) DO UPDATE SET certificate_id = EXCLUDED.certificate_id
#         RETURNING *""", (uuid4(), user_id, certificate_id)
#     ).fetchone()
#
# def get_bookmarks(connection: Connection, user_id: UUID) -> list[dict]:
#     """인증된 사용자의 북마크 목록을 조회한다."""
#     return connection.execute(
#         "SELECT * FROM bookmarks WHERE user_id = %s ORDER BY created_at DESC", (user_id,)
#     ).fetchall()
#
# def delete_bookmark(connection: Connection, user_id: UUID, certificate_id: UUID) -> bool:
#     """인증된 사용자 본인의 북마크만 삭제한다."""
#     return connection.execute(
#         "DELETE FROM bookmarks WHERE user_id = %s AND certificate_id = %s", (user_id, certificate_id)
#     ).rowcount > 0

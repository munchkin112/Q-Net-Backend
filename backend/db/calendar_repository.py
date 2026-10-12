"""Calendar 등록 작업과 Google 이벤트의 DB 조회·저장을 담당한다."""

from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb


def get_calendar_registration(
    connection: Connection,
    user_id: UUID,
    idempotency_key: UUID,
) -> dict | None:
    """사용자 멱등 키에 해당하는 등록 작업을 조회한다."""
    return connection.execute(
        """SELECT * FROM calendar_registrations
        WHERE user_id = %s AND idempotency_key = %s""",
        (user_id, idempotency_key),
    ).fetchone()


def list_schedules_for_calendar_registration(
    connection: Connection,
    certificate_id: UUID,
    schedule_ids: list[UUID],
) -> list[dict]:
    """선택한 종목의 일정만 자격증명과 함께 조회한다."""
    return connection.execute(
        """SELECT schedules.*, certificates.name AS certificate_name
        FROM schedules
        JOIN certificates ON certificates.id = schedules.certificate_id
        WHERE schedules.certificate_id = %s AND schedules.id = ANY(%s)
        ORDER BY schedules.phase""",
        (certificate_id, schedule_ids),
    ).fetchall()


def create_calendar_registration(
    connection: Connection,
    user_id: UUID,
    idempotency_key: UUID,
    request_hash: str,
    certificate_id: UUID,
    year: int,
    round_key: str,
    round_label: str,
    event_types: list[str],
    request_events: list[dict],
    excluded_items: list[dict],
) -> tuple[dict, bool]:
    """회차 계획·멱등 요청·대기 이벤트를 저장한다. 외부 Google 호출은 하지 않는다."""
    plan = connection.execute(
        """INSERT INTO user_exam_plans (
            id, user_id, certificate_id, year, round_key, round_label,
            selected_event_types, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        ON CONFLICT (user_id, certificate_id, year, round_key)
        DO UPDATE SET round_label = EXCLUDED.round_label,
                      selected_event_types = EXCLUDED.selected_event_types,
                      updated_at = now()
        RETURNING id""",
        (
            uuid4(), user_id, certificate_id, year, round_key, round_label,
            Jsonb(event_types),
        ),
    ).fetchone()

    registration = connection.execute(
        """INSERT INTO calendar_registrations (
            id, user_id, idempotency_key, request_hash, exam_plan_id,
            request_events, excluded_items, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        ON CONFLICT (user_id, idempotency_key) DO NOTHING
        RETURNING *""",
        (
            uuid4(), user_id, idempotency_key, request_hash, plan["id"],
            Jsonb(request_events), Jsonb(excluded_items),
        ),
    ).fetchone()

    if registration is None:
        registration = get_calendar_registration(connection, user_id, idempotency_key)
        if registration is None:
            raise RuntimeError("Calendar 등록 요청을 다시 조회할 수 없습니다.")
        return registration, False

    for event in request_events:
        connection.execute(
            """INSERT INTO calendar_events (
                id, exam_plan_id, registration_id, user_id, certificate_id,
                schedule_id, item_key, event_type, phase, starts_on, ends_on,
                title, description, source_url, schedule_version,
                google_event_id, sync_status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending'
            )
            ON CONFLICT (user_id, schedule_id, item_key) DO NOTHING""",
            (
                uuid4(), plan["id"], registration["id"], user_id, certificate_id,
                UUID(event["schedule_id"]), event["item_key"], event["event_type"],
                event["phase"], event["starts_on"], event["ends_on"],
                event["title"], event["description"], event["source_url"],
                event["schedule_version"], event["google_event_id"],
            ),
        )

    return registration, True


def get_calendar_event(
    connection: Connection,
    user_id: UUID,
    schedule_id: UUID,
    item_key: str,
) -> dict | None:
    """사용자·일정·이벤트 식별자로 저장된 이벤트를 조회한다."""
    return connection.execute(
        """SELECT * FROM calendar_events
        WHERE user_id = %s AND schedule_id = %s AND item_key = %s""",
        (user_id, schedule_id, item_key),
    ).fetchone()


def update_calendar_event_result(
    connection: Connection,
    event_id: UUID,
    status: str,
    google_event_id: str | None = None,
    html_link: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    retryable: bool = False,
) -> dict:
    """외부 이벤트 등록 결과를 보관한다."""
    return connection.execute(
        """UPDATE calendar_events
        SET sync_status = %s,
            google_event_id = COALESCE(%s, google_event_id),
            html_link = COALESCE(%s, html_link),
            error_code = %s,
            error_message = %s,
            retryable = %s,
            updated_at = now()
        WHERE id = %s
        RETURNING *""",
        (status, google_event_id, html_link, error_code, error_message, retryable, event_id),
    ).fetchone()


def update_calendar_registration_result(
    connection: Connection,
    registration_id: UUID,
    status: str,
    response: dict,
) -> None:
    """항목별 처리 결과를 멱등 요청에 함께 저장한다."""
    connection.execute(
        """UPDATE calendar_registrations
        SET status = %s, response = %s, updated_at = now()
        WHERE id = %s""",
        (status, Jsonb(response), registration_id),
    )
    connection.execute(
        """UPDATE user_exam_plans
        SET status = %s, updated_at = now()
        WHERE id = (SELECT exam_plan_id FROM calendar_registrations WHERE id = %s)""",
        (status, registration_id),
    )


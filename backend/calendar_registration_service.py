"""사용자 선택을 검증하고 기본 Google Calendar에 일정별 등록한다."""

import hashlib
import json
from datetime import date, datetime
from uuid import UUID

import httpx
from psycopg import Connection

from backend.calendar_google import CalendarGoogleError, GoogleCalendarClient
from backend.calendar_schemas import CalendarRegisterRequest
from backend.calendar_service import (
    build_selected_calendar_events,
    get_calendar_connection_credential,
)
from backend.db import calendar_repository
from backend.db.connection import database_connection


class CalendarRegistrationError(Exception):
    """Calendar API가 반환할 HTTP 상태·오류 코드를 보관한다."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _as_date(value: date | datetime | str | None) -> date | None:
    """시험 일정 값을 날짜로 통일한다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def _validate_schedule_dates(schedule: dict) -> None:
    """접수·시험·발표일의 순서와 실제 접수 구간을 검증한다."""
    periods = schedule.get("registration_periods") or []
    normalized_periods = []
    for period in periods:
        starts_on = _as_date(period.get("starts_on"))
        ends_on = _as_date(period.get("ends_on"))
        if starts_on is None or ends_on is None or starts_on > ends_on:
            raise CalendarRegistrationError(
                422, "INVALID_SCHEDULE", "공식 원서접수 기간의 날짜 순서를 확인할 수 없습니다."
            )
        normalized_periods.append((starts_on, ends_on))

    for previous, current in zip(normalized_periods, normalized_periods[1:]):
        if previous[1] >= current[0]:
            raise CalendarRegistrationError(
                422, "INVALID_SCHEDULE", "공식 원서접수 기간이 겹치거나 순서가 올바르지 않습니다."
            )

    registration_start = _as_date(schedule.get("registration_start"))
    registration_end = _as_date(schedule.get("registration_end"))
    if normalized_periods:
        first_start = normalized_periods[0][0]
        last_end = normalized_periods[-1][1]
        if registration_start is not None and registration_start != first_start:
            raise CalendarRegistrationError(
                422, "INVALID_SCHEDULE", "원서접수 전체 기간과 실제 접수 구간이 일치하지 않습니다."
            )
        if registration_end is not None and registration_end != last_end:
            raise CalendarRegistrationError(
                422, "INVALID_SCHEDULE", "원서접수 전체 기간과 실제 접수 구간이 일치하지 않습니다."
            )
        registration_start = first_start
        registration_end = last_end

    ordered_dates = [
        registration_start,
        registration_end,
        _as_date(schedule.get("exam_start")),
        _as_date(schedule.get("exam_end")),
        _as_date(schedule.get("result_date")),
    ]
    previous_date = None
    for current_date in ordered_dates:
        if current_date is None:
            continue
        if previous_date is not None and current_date < previous_date:
            raise CalendarRegistrationError(
                422, "INVALID_SCHEDULE", "공식 접수·시험·합격발표 날짜의 순서를 확인할 수 없습니다."
            )
        previous_date = current_date


def validate_selected_schedules(
    request: CalendarRegisterRequest,
    schedules: list[dict],
) -> tuple[int, str, str]:
    """선택 일정의 소속·회차·조회 버전이 요청과 일치하는지 확인한다."""
    if len(schedules) != len(request.schedule_ids):
        raise CalendarRegistrationError(
            422,
            "INVALID_SCHEDULE_SELECTION",
            "선택한 시험 일정 중 자격증과 연결되지 않은 일정이 있습니다.",
        )

    schedule_ids = {schedule["id"] for schedule in schedules}
    if schedule_ids != set(request.schedule_ids):
        raise CalendarRegistrationError(
            422,
            "INVALID_SCHEDULE_SELECTION",
            "선택한 시험 일정을 다시 조회해주세요.",
        )

    rounds = set()
    for schedule in schedules:
        if schedule["certificate_id"] != request.certificate_id:
            raise CalendarRegistrationError(
                422,
                "INVALID_SCHEDULE_SELECTION",
                "다른 자격증의 시험 일정은 함께 등록할 수 없습니다.",
            )
        _validate_schedule_dates(schedule)
        rounds.add((schedule["year"], schedule["round_key"], schedule["round_label"]))

        expected_version = request.schedule_versions[schedule["id"]]
        if _as_datetime(schedule["updated_at"]) != expected_version:
            raise CalendarRegistrationError(
                409,
                "SCHEDULE_CHANGED",
                "시험 일정이 변경되었습니다. 최신 일정을 다시 조회해주세요.",
            )

    if len(rounds) != 1:
        raise CalendarRegistrationError(
            422,
            "INVALID_SCHEDULE_SELECTION",
            "한 번의 요청에는 같은 시험회차의 일정만 선택할 수 있습니다.",
        )

    year, round_key, round_label = next(iter(rounds))
    return year, round_key, round_label


def create_calendar_request_hash(request: CalendarRegisterRequest) -> str:
    """순서 차이만 있는 동일 선택 요청에 같은 멱등 해시를 만든다."""
    request_data = {
        "certificate_id": str(request.certificate_id),
        "schedule_ids": sorted(str(value) for value in request.schedule_ids),
        "schedule_versions": {
            str(key): value.isoformat()
            for key, value in sorted(request.schedule_versions.items(), key=lambda item: str(item[0]))
        },
        "event_types": sorted(request.event_types),
    }
    serialized = json.dumps(request_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _as_datetime(value: datetime | str) -> datetime:
    """DB 또는 JSON 시간 값을 시간대가 포함된 datetime으로 바꾼다."""
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("시험 일정 조회 시각에 시간대가 없습니다.")
    return parsed


def _as_json_event(event: dict, connection_id: UUID) -> dict:
    """일정 이벤트를 DB에 저장 가능한 값으로 만들고 결정적 Google ID를 부여한다."""
    schedule_id = str(event["schedule_id"])
    item_key = event["item_key"]
    google_identity = f"{connection_id}:{schedule_id}:{item_key}"
    google_event_id = hashlib.sha256(google_identity.encode("utf-8")).hexdigest()
    return {
        **event,
        "schedule_id": schedule_id,
        "starts_on": event["starts_on"].isoformat(),
        "ends_on": event["ends_on"].isoformat(),
        "schedule_version": _as_datetime(event["schedule_version"]).isoformat(),
        "google_event_id": google_event_id,
    }


def _calendar_status(items: list[dict], excluded_items: list[dict]) -> tuple[str, str]:
    """항목별 성공·실패에 맞춰 요청 전체의 결과 상태와 안내를 정한다."""
    statuses = [item["status"] for item in items]
    if "unknown" in statuses:
        return "pending_confirmation", "일부 일정의 등록 결과를 확인 중입니다. 같은 요청으로 다시 확인해주세요."
    successful = sum(status in {"created", "already_registered"} for status in statuses)
    failed = sum(status == "failed" for status in statuses)
    if failed and successful == 0:
        return "failed", "선택한 일정을 등록하지 못했습니다. 항목별 오류를 확인해주세요."
    if failed or excluded_items:
        return "partial", "확인 가능한 일정만 등록했습니다. 제외·실패 항목을 확인해주세요."
    return "completed", "선택한 일정을 Google Calendar에 등록했습니다."


def _response_item(event: dict, status: str, **details) -> dict:
    """DB 처리 결과를 API 응답 항목으로 제한한다."""
    return {
        "item_key": event["item_key"],
        "event_type": event["event_type"],
        "status": status,
        "google_event_id": details.get("google_event_id"),
        "html_link": details.get("html_link"),
        "code": details.get("code"),
        "message": details.get("message"),
        "retryable": bool(details.get("retryable", False)),
    }


def _find_current_schedule_versions(connection, request_events: list[dict], certificate_id: UUID) -> dict[UUID, datetime]:
    """기존 미완료 작업을 재시도하기 전 최신 일정 버전을 확인한다."""
    schedule_ids = list(dict.fromkeys(UUID(event["schedule_id"]) for event in request_events))
    if not schedule_ids:
        return {}
    schedules = calendar_repository.list_schedules_for_calendar_registration(
        connection, certificate_id, schedule_ids
    )
    return {schedule["id"]: _as_datetime(schedule["updated_at"]) for schedule in schedules}


def _load_google_access_token(connection, connection_id: UUID, google_client: GoogleCalendarClient) -> str:
    """Calendar 연결의 암호화 토큰을 읽어 액세스 토큰을 발급받는다."""
    try:
        credential = get_calendar_connection_credential(connection, connection_id)
    except PermissionError:
        raise CalendarRegistrationError(
            403,
            "GOOGLE_CALENDAR_PERMISSION_REQUIRED",
            "Google Calendar를 다시 연결해주세요.",
        ) from None
    if credential is None:
        raise CalendarRegistrationError(
            403,
            "GOOGLE_CALENDAR_PERMISSION_REQUIRED",
            "Google Calendar를 다시 연결해주세요.",
        )

    try:
        return google_client.refresh_access_token(credential[0])
    except CalendarGoogleError as error:
        status_code = 403 if error.permission_required else 503
        raise CalendarRegistrationError(status_code, error.code, error.message) from None


def _process_registration(
    connection: Connection,
    connection_id: UUID,
    registration: dict,
    request_events: list[dict],
    excluded_items: list[dict],
    access_token: str,
    google_client: GoogleCalendarClient,
    certificate_id: UUID,
) -> dict:
    """이벤트별 중복 확인·Google 등록·상태 저장을 순서대로 처리한다."""
    items = []
    current_versions = _find_current_schedule_versions(
        connection, request_events, certificate_id
    )

    for event in request_events:
        schedule_id = UUID(event["schedule_id"])
        saved = calendar_repository.get_calendar_event(
            connection, connection_id, schedule_id, event["item_key"]
        )
        if saved is None:
            items.append(_response_item(
                event, "failed", code="CALENDAR_EVENT_RECORD_MISSING",
                message="등록 결과 저장 정보를 찾을 수 없습니다.", retryable=False,
            ))
            continue

        if saved["sync_status"] == "created":
            status = "created" if saved["registration_id"] == registration["id"] else "already_registered"
            items.append(_response_item(
                event, status,
                google_event_id=saved["google_event_id"],
                html_link=saved.get("html_link"),
            ))
            continue

        # 이전 코드가 API 미활성화를 권한 오류로 저장한 경우에도 설정 보정 후 다시 확인한다.
        if (saved["sync_status"] == "failed" and not saved.get("retryable", False)
                and saved.get("error_code") not in {"GOOGLE_CALENDAR_PERMISSION_DENIED", "GOOGLE_CALENDAR_REAUTH_REQUIRED"}):
            items.append(_response_item(
                event, "failed", code=saved.get("error_code"),
                message=saved.get("error_message"), retryable=False,
            ))
            continue

        saved_version = _as_datetime(saved["schedule_version"])
        event_version = _as_datetime(event["schedule_version"])
        if saved_version != event_version:
            updated = calendar_repository.update_calendar_event_result(
                connection,
                saved["id"],
                "failed",
                error_code="SCHEDULE_CHANGED",
                error_message="일정이 변경되어 등록하지 않았습니다. 최신 일정을 다시 선택해주세요.",
                retryable=False,
            )
            connection.commit()
            items.append(_response_item(
                event, "failed", code=updated["error_code"],
                message=updated["error_message"], retryable=False,
            ))
            continue

        expected_version = _as_datetime(event["schedule_version"])
        current_version = current_versions.get(schedule_id)
        if current_version is None or current_version != expected_version:
            updated = calendar_repository.update_calendar_event_result(
                connection,
                saved["id"],
                "failed",
                error_code="SCHEDULE_CHANGED",
                error_message="일정이 변경되어 등록하지 않았습니다. 최신 일정을 다시 선택해주세요.",
                retryable=False,
            )
            connection.commit()
            items.append(_response_item(
                event, "failed", code=updated["error_code"],
                message=updated["error_message"], retryable=False,
            ))
            continue

        try:
            google_result = google_client.ensure_event(access_token, event)
            updated = calendar_repository.update_calendar_event_result(
                connection,
                saved["id"],
                "created",
                google_event_id=google_result["google_event_id"],
                html_link=google_result.get("html_link"),
            )
            connection.commit()
            items.append(_response_item(
                event,
                google_result["status"],
                google_event_id=updated["google_event_id"],
                html_link=updated.get("html_link"),
            ))
        except CalendarGoogleError as error:
            status = "unknown" if error.unknown else "failed"
            updated = calendar_repository.update_calendar_event_result(
                connection,
                saved["id"],
                status,
                error_code=error.code,
                error_message=error.message,
                retryable=error.retryable,
            )
            connection.commit()
            items.append(_response_item(
                event, status, code=error.code,
                message=error.message, retryable=error.retryable,
            ))

    overall_status, message = _calendar_status(items, excluded_items)
    response = {
        "registration_id": str(registration["id"]),
        "status": overall_status,
        "items": items,
        "excluded_items": excluded_items,
        "message": message,
    }
    calendar_repository.update_calendar_registration_result(
        connection, registration["id"], overall_status, response
    )
    connection.commit()
    return response


def register_calendar_events(
    connection_id: UUID,
    request: CalendarRegisterRequest,
    idempotency_key: UUID,
) -> dict:
    """선택 항목만 검증·저장·등록하고 재요청 때 중복 생성을 막는다."""
    request_hash = create_calendar_request_hash(request)

    with database_connection() as connection:
        registration = calendar_repository.get_calendar_registration(
            connection, connection_id, idempotency_key
        )
        is_existing_request = registration is not None

        if is_existing_request:
            if registration["request_hash"] != request_hash:
                raise CalendarRegistrationError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "같은 Idempotency-Key를 다른 선택 내용에 사용할 수 없습니다.",
                )
            stored_response = registration.get("response")
            if stored_response and not _has_retryable_items(stored_response):
                return stored_response
            request_events = registration["request_events"]
            excluded_items = registration["excluded_items"] or []
            # 같은 멱등 키의 요청 해시를 확인했으므로 요청의 종목 ID를 재사용한다.
            # calendar_registrations 테이블에는 certificate_id 컬럼이 없다.
            certificate_id = request.certificate_id
        else:
            schedules = calendar_repository.list_schedules_for_calendar_registration(
                connection, request.certificate_id, request.schedule_ids
            )
            year, round_key, round_label = validate_selected_schedules(request, schedules)
            events, excluded_items = build_selected_calendar_events(
                schedules, request.event_types
            )
            if not events:
                raise CalendarRegistrationError(
                    422,
                    "NO_REGISTERABLE_EVENTS",
                    "선택한 항목에서 등록 가능한 공식 일정을 찾지 못했습니다.",
                )
            request_events = [_as_json_event(event, connection_id) for event in events]
            certificate_id = request.certificate_id

        connection.commit()

        if not request_events:
            raise CalendarRegistrationError(
                422,
                "NO_REGISTERABLE_EVENTS",
                "등록할 수 있는 일정 항목이 없습니다.",
            )

        with httpx.Client(timeout=15) as http_client:
            google_client = GoogleCalendarClient(http_client)
            access_token = _load_google_access_token(connection, connection_id, google_client)
            connection.commit()

            if not is_existing_request:
                registration, created = calendar_repository.create_calendar_registration(
                    connection,
                    connection_id,
                    idempotency_key,
                    request_hash,
                    certificate_id,
                    year,
                    round_key,
                    round_label,
                    request.event_types,
                    request_events,
                    excluded_items,
                )
                if not created and registration["request_hash"] != request_hash:
                    raise CalendarRegistrationError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "같은 Idempotency-Key를 다른 선택 내용에 사용할 수 없습니다.",
                    )
                connection.commit()

            return _process_registration(
                connection,
                connection_id,
                registration,
                request_events,
                excluded_items,
                access_token,
                google_client,
                certificate_id,
            )


def _has_retryable_items(response: dict) -> bool:
    """결과 불명 또는 재시도 가능한 실패가 있는지 확인한다."""
    return any(
        item.get("status") == "unknown"
        or (item.get("status") == "failed" and (
            item.get("retryable", False)
            or item.get("code") in {"GOOGLE_CALENDAR_PERMISSION_DENIED", "GOOGLE_CALENDAR_REAUTH_REQUIRED"}
        ))
        for item in response.get("items", [])
    )


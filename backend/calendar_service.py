"""Google Calendar 이벤트를 구성하고 권한 갱신 자격 증명을 다룬다."""

import binascii
import hashlib
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from psycopg import Connection

from backend.settings import load_settings


CALENDAR_EVENT_TYPES = {
    "registration",
    "written_exam",
    "practical_exam",
    "result",
}
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
CALENDAR_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60

PHASE_LABELS = {
    "written": "필기",
    "practical": "실기",
    "interview": "면접",
    "first": "1차",
    "second": "2차",
    "other": "시험",
}


def _calendar_date(value: date | datetime | str | None) -> date | None:
    """DB·JSON에서 읽은 날짜를 날짜 객체로 통일한다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    raise ValueError("일정 날짜 형식이 올바르지 않습니다.")


def _make_calendar_event(
    schedule: dict,
    event_type: str,
    item_key: str,
    starts_on: date,
    ends_on: date,
    source_url: str | None = None,
) -> dict:
    """검증된 일정 한 건을 Google 종일 이벤트 입력값으로 바꾼다."""
    phase_label = PHASE_LABELS.get(schedule.get("phase"), "시험")
    certificate_name = schedule.get("certificate_name", "자격증")
    round_label = schedule.get("round_label", "시험회차")

    if event_type == "registration":
        event_label = "원서접수 기간"
        title = f"{certificate_name} {round_label} {phase_label} 원서접수"
    elif event_type == "written_exam":
        event_label = "필기시험"
        title = f"{certificate_name} {round_label} 필기시험"
    elif event_type == "practical_exam":
        event_label = "실기시험"
        title = f"{certificate_name} {round_label} 실기시험"
    else:
        event_label = f"{phase_label} 합격발표"
        title = f"{certificate_name} {round_label} {phase_label} 합격발표"

    official_source = source_url or schedule.get("source_url")
    description = (
        f"{event_label} 일정입니다. 날짜와 상세 안내는 큐넷 공식 자료를 확인해주세요.\n"
        f"공식 출처: {official_source}"
    )
    return {
        "item_key": item_key,
        "event_type": event_type,
        "schedule_id": schedule["id"],
        "phase": schedule["phase"],
        "starts_on": starts_on,
        "ends_on": ends_on,
        "title": title,
        "description": description,
        "source_url": official_source,
        "schedule_version": schedule["updated_at"],
    }


def build_selected_calendar_events(
    schedules: list[dict],
    selected_event_types: list[str],
) -> tuple[list[dict], list[dict]]:
    """사용자가 선택한 네 종류만 일정 행에서 만들고 누락 항목은 사유와 반환한다."""
    unknown_types = set(selected_event_types) - CALENDAR_EVENT_TYPES
    if unknown_types:
        raise ValueError("지원하지 않는 Calendar 일정 종류가 있습니다.")

    events: list[dict] = []
    excluded_items: list[dict] = []

    for event_type in selected_event_types:
        created_for_type = 0
        specific_exclusions_for_type = 0

        if event_type == "registration":
            for schedule in schedules:
                periods = schedule.get("registration_periods") or []
                if not periods:
                    start = _calendar_date(schedule.get("registration_start"))
                    end = _calendar_date(schedule.get("registration_end"))
                    if start is not None and end is not None:
                        periods = [{"starts_on": start, "ends_on": end}]
                    else:
                        excluded_items.append({
                            "event_type": event_type,
                            "reason": "해당 회차의 원서접수 기간을 확인할 수 없어 등록하지 않았습니다.",
                            "schedule_id": str(schedule["id"]),
                            "period_index": None,
                        })
                        specific_exclusions_for_type += 1

                for period_index, period in enumerate(periods, start=1):
                    start = _calendar_date(period.get("starts_on"))
                    end = _calendar_date(period.get("ends_on"))
                    source_url = period.get("source_url") or schedule.get("source_url")
                    reason = None
                    if start is None or end is None:
                        reason = "원서접수 시작일 또는 종료일을 확인할 수 없어 해당 기간을 등록하지 않았습니다."
                    elif start > end:
                        reason = "원서접수 시작일이 종료일보다 늦어 해당 기간을 등록하지 않았습니다."
                    elif not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
                        reason = "공식 출처 URL을 확인할 수 없어 해당 기간을 등록하지 않았습니다."

                    if reason is not None:
                        excluded_items.append({
                            "event_type": event_type,
                            "reason": reason,
                            "schedule_id": str(schedule["id"]),
                            "period_index": period_index,
                        })
                        specific_exclusions_for_type += 1
                        continue

                    phase = schedule.get("phase", "other")
                    item_key = f"{phase}-registration-{start.isoformat()}-{end.isoformat()}"
                    events.append(_make_calendar_event(
                        schedule, event_type, item_key, start, end, source_url
                    ))
                    created_for_type += 1

        elif event_type in {"written_exam", "practical_exam"}:
            requested_phase = "written" if event_type == "written_exam" else "practical"
            phase_schedules = [row for row in schedules if row.get("phase") == requested_phase]
            for schedule in phase_schedules:
                start = _calendar_date(schedule.get("exam_start"))
                end = _calendar_date(schedule.get("exam_end")) or start
                source_url = schedule.get("source_url")
                if start is None or end is None or start > end:
                    continue
                if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
                    continue
                events.append(_make_calendar_event(
                    schedule, event_type, f"{requested_phase}-exam", start, end
                ))
                created_for_type += 1

        else:
            for schedule in schedules:
                result_date = _calendar_date(schedule.get("result_date"))
                source_url = schedule.get("source_url")
                if result_date is None:
                    continue
                if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
                    continue
                phase = schedule.get("phase", "other")
                events.append(_make_calendar_event(
                    schedule, event_type, f"{phase}-result", result_date, result_date
                ))
                created_for_type += 1

        if created_for_type == 0 and specific_exclusions_for_type == 0:
            missing_messages = {
                "registration": "선택한 일정에서 확인할 수 있는 원서접수 기간이 없습니다.",
                "written_exam": "선택한 회차에서 필기시험 날짜를 확인할 수 없습니다.",
                "practical_exam": "선택한 회차에서 실기시험 날짜를 확인할 수 없습니다.",
                "result": "선택한 일정에서 합격발표일을 확인할 수 없습니다.",
            }
            excluded_items.append({
                "event_type": event_type,
                "reason": missing_messages[event_type],
            })

    return events, excluded_items


def get_google_token_fernet() -> Fernet:
    """전용 환경변수에서 Google 토큰 암호화 키를 읽는다."""
    load_settings()
    encryption_key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY 환경변수가 필요합니다.")

    try:
        return Fernet(encryption_key.encode("ascii"))
    except (binascii.Error, UnicodeError, TypeError, ValueError):
        raise RuntimeError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY 형식이 올바르지 않습니다."
        ) from None


def create_google_calendar_credential(
    connection: Connection,
    user_id: UUID,
    refresh_token: str | None,
    scopes: str,
) -> bool:
    """Google 갱신 토큰을 암호화 저장하고 Calendar 연결 여부를 반환한다.

    호출자가 전달한 DB 연결을 사용하며 커밋하지 않는다.
    Google이 새 토큰을 반환하지 않으면 기존 저장값을 유지한다.
    """
    if not isinstance(user_id, UUID):
        raise ValueError("Google Calendar 사용자 ID가 유효하지 않습니다.")
    if not isinstance(scopes, str):
        raise ValueError("Google Calendar 권한 정보 형식이 올바르지 않습니다.")

    if refresh_token is None:
        existing_credential = connection.execute(
            """UPDATE google_calendar_credentials
            SET scopes = COALESCE(NULLIF(btrim(%s), ''), scopes),
                updated_at = now()
            WHERE user_id = %s
            RETURNING user_id""",
            (scopes, user_id),
        ).fetchone()
        return existing_credential is not None

    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise ValueError("Google Calendar 갱신 토큰 형식이 올바르지 않습니다.")

    token_cipher = get_google_token_fernet()
    encrypted_refresh_token = token_cipher.encrypt(
        refresh_token.encode("utf-8")
    ).decode("ascii")

    saved_credential = connection.execute(
        """INSERT INTO google_calendar_credentials (
            user_id,
            refresh_token_ciphertext,
            scopes
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            refresh_token_ciphertext = EXCLUDED.refresh_token_ciphertext,
            scopes = EXCLUDED.scopes,
            updated_at = now()
        RETURNING user_id""",
        (user_id, encrypted_refresh_token, scopes),
    ).fetchone()

    return saved_credential is not None


def get_google_calendar_credential(
    connection: Connection,
    user_id: UUID,
) -> tuple[str, str] | None:
    """로그인 때 암호화 저장한 Calendar 갱신 토큰과 권한을 가져온다."""
    if not isinstance(user_id, UUID):
        raise ValueError("Google Calendar 사용자 ID가 유효하지 않습니다.")

    row = connection.execute(
        """SELECT refresh_token_ciphertext, scopes
        FROM google_calendar_credentials WHERE user_id = %s""",
        (user_id,),
    ).fetchone()
    if row is None:
        return None

    token_cipher = get_google_token_fernet()
    try:
        refresh_token = token_cipher.decrypt(
            row["refresh_token_ciphertext"].encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, UnicodeError, AttributeError, KeyError):
        raise RuntimeError("Google Calendar 자격 증명을 복호화할 수 없습니다.") from None

    scopes = row.get("scopes") or ""
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise RuntimeError("Google Calendar 갱신 토큰을 읽을 수 없습니다.")
    if GOOGLE_CALENDAR_SCOPE not in scopes.split():
        raise PermissionError("Google Calendar 권한 동의가 필요합니다.")

    return refresh_token, scopes


def create_calendar_connection(
    connection: Connection,
    refresh_token: str,
    scopes: str,
) -> str:
    """Calendar 전용 연결을 저장하고 브라우저에 전달할 비밀 세션값을 반환한다."""
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise ValueError("Google Calendar 갱신 토큰이 필요합니다.")
    if not isinstance(scopes, str) or GOOGLE_CALENDAR_SCOPE not in scopes.split():
        raise PermissionError("Google Calendar 권한 동의가 필요합니다.")

    session_token = secrets.token_urlsafe(32)
    session_token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    encrypted_refresh_token = get_google_token_fernet().encrypt(
        refresh_token.encode("utf-8")
    ).decode("ascii")
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=CALENDAR_SESSION_TTL_SECONDS
    )

    connection.execute(
        """INSERT INTO calendar_connections (
            id, session_token_hash, refresh_token_ciphertext, scopes, expires_at
        ) VALUES (%s, %s, %s, %s, %s)""",
        (uuid4(), session_token_hash, encrypted_refresh_token, scopes, expires_at),
    )
    return session_token


def get_calendar_connection_id(
    connection: Connection,
    session_token: str,
) -> UUID | None:
    """쿠키 토큰의 해시·유효기간·폐기 여부를 확인해 연결 ID를 반환한다."""
    if not isinstance(session_token, str) or not session_token:
        return None
    if len(session_token) > 256 or not session_token.isascii():
        return None

    session_token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    row = connection.execute(
        """SELECT id FROM calendar_connections
        WHERE session_token_hash = %s
          AND expires_at > now()
          AND revoked_at IS NULL""",
        (session_token_hash,),
    ).fetchone()
    if row is None:
        return None
    return row["id"]


def get_calendar_connection_credential(
    connection: Connection,
    connection_id: UUID,
) -> tuple[str, str] | None:
    """유효한 Calendar 전용 연결에서 복호화한 갱신 토큰을 읽는다."""
    if not isinstance(connection_id, UUID):
        raise ValueError("Google Calendar 연결 ID가 올바르지 않습니다.")

    row = connection.execute(
        """SELECT refresh_token_ciphertext, scopes FROM calendar_connections
        WHERE id = %s AND expires_at > now() AND revoked_at IS NULL""",
        (connection_id,),
    ).fetchone()
    if row is None:
        return None

    token_cipher = get_google_token_fernet()
    try:
        refresh_token = token_cipher.decrypt(
            row["refresh_token_ciphertext"].encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, UnicodeError, AttributeError, KeyError):
        raise RuntimeError("Google Calendar 자격 증명을 복호화할 수 없습니다.") from None

    scopes = row.get("scopes") or ""
    if not refresh_token.strip():
        raise RuntimeError("Google Calendar 갱신 토큰을 읽을 수 없습니다.")
    if GOOGLE_CALENDAR_SCOPE not in scopes.split():
        raise PermissionError("Google Calendar 권한 동의가 필요합니다.")
    return refresh_token, scopes


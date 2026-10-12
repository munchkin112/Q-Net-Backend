"""Google Calendar OAuth 토큰 갱신과 종일 이벤트 등록을 처리한다."""

from datetime import date, datetime, timedelta
from urllib.parse import quote

import httpx

from backend.auth_settings import get_google_auth_settings


TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class CalendarGoogleError(Exception):
    """Google API 실패를 사용자에게 안전한 코드와 재시도 여부로 전달한다."""

    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool,
        unknown: bool = False,
        permission_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.unknown = unknown
        self.permission_required = permission_required


def _calendar_access_error(response: httpx.Response) -> CalendarGoogleError:
    """API 미활성화와 사용자 권한 실패를 구분한다. Google 응답 원문은 노출하지 않는다."""
    try:
        body = response.json()
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error, dict):
            error = {}
        reasons = {item.get("reason") for item in error.get("errors", []) if isinstance(item, dict)}
        reasons.update(item.get("reason") for item in error.get("details", []) if isinstance(item, dict))
    except (ValueError, TypeError):
        reasons = set()
    if response.status_code == 403 and reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
        return CalendarGoogleError(
            "GOOGLE_CALENDAR_API_DISABLED",
            "백엔드 OAuth 클라이언트의 Google Cloud 프로젝트에서 Google Calendar API를 사용 설정해주세요.",
            retryable=True,
        )
    return CalendarGoogleError(
        "GOOGLE_CALENDAR_PERMISSION_DENIED",
        "Google Calendar 권한이 만료되었거나 부족합니다. Calendar를 다시 연결해주세요.",
        retryable=False,
        permission_required=True,
    )


class GoogleCalendarClient:
    """기본 캘린더에 이벤트를 만드는 Google API 호출을 제공한다."""

    def __init__(self, http_client: httpx.Client) -> None:
        self.http_client = http_client

    def refresh_access_token(self, refresh_token: str) -> str:
        """서버에 보관한 Google 갱신 토큰으로 짧은 수명의 액세스 토큰을 받는다."""
        settings = get_google_auth_settings()
        try:
            response = self.http_client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError:
            raise CalendarGoogleError(
                "GOOGLE_TOKEN_SERVICE_UNAVAILABLE",
                "Google 인증 서버에 연결할 수 없습니다.",
                retryable=True,
            ) from None

        if response.status_code >= 400:
            try:
                error_code = response.json().get("error")
            except (ValueError, AttributeError):
                error_code = None
            if error_code == "invalid_grant":
                raise CalendarGoogleError(
                    "GOOGLE_CALENDAR_REAUTH_REQUIRED",
                    "Google Calendar 권한이 만료되었습니다. 다시 로그인해주세요.",
                    retryable=False,
                    permission_required=True,
                )
            raise CalendarGoogleError(
                "GOOGLE_TOKEN_REFRESH_FAILED",
                "Google Calendar 토큰을 갱신할 수 없습니다.",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            access_token = response.json().get("access_token")
        except (ValueError, AttributeError):
            access_token = None
        if not isinstance(access_token, str) or not access_token.strip():
            raise CalendarGoogleError(
                "GOOGLE_TOKEN_REFRESH_FAILED",
                "Google Calendar 액세스 토큰 응답을 확인할 수 없습니다.",
                retryable=False,
            )
        return access_token

    def get_event(self, access_token: str, google_event_id: str) -> dict | None:
        """결정적 Google 이벤트 ID로 이전 등록 여부를 확인한다."""
        event_url = CALENDAR_EVENTS_URL + "/" + quote(google_event_id, safe="")
        try:
            response = self.http_client.get(
                event_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_UNAVAILABLE",
                "Google Calendar에서 기존 일정을 확인할 수 없습니다.",
                retryable=True,
            ) from None

        if response.status_code == 404:
            return None
        if response.status_code in {401, 403}:
            raise _calendar_access_error(response)
        if response.status_code == 429:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_RATE_LIMITED",
                "Google Calendar 요청 한도에 도달했습니다. 잠시 후 다시 시도해주세요.",
                retryable=True,
            )
        if response.status_code >= 400:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_UNAVAILABLE",
                "Google Calendar에서 일정을 확인할 수 없습니다.",
                retryable=response.status_code >= 500,
            )
        try:
            event = response.json()
        except ValueError:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_INVALID_RESPONSE",
                "Google Calendar 응답 형식을 확인할 수 없습니다.",
                retryable=False,
            ) from None
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_INVALID_RESPONSE",
                "Google Calendar에서 기존 일정 정보를 확인할 수 없습니다.",
                retryable=True,
            )
        return event

    def ensure_event(self, access_token: str, event: dict) -> dict:
        """이전 등록을 확인한 뒤 없을 때만 기본 캘린더에 종일 이벤트를 만든다."""
        existing = self.get_event(access_token, event["google_event_id"])
        if existing is not None:
            return {
                "status": "already_registered",
                "google_event_id": existing.get("id", event["google_event_id"]),
                "html_link": existing.get("htmlLink"),
            }

        starts_on = _as_date(event["starts_on"])
        ends_on = _as_date(event["ends_on"])
        if starts_on > ends_on:
            raise ValueError("Calendar 이벤트 시작일은 종료일보다 늦을 수 없습니다.")

        payload = {
            "id": event["google_event_id"],
            "summary": event["title"],
            "description": event["description"],
            "start": {"date": starts_on.isoformat()},
            # Google 종일 이벤트의 종료 날짜는 포함하지 않는 다음 날짜다.
            "end": {"date": (ends_on + timedelta(days=1)).isoformat()},
        }
        try:
            response = self.http_client.post(
                CALENDAR_EVENTS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        except httpx.HTTPError:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_RESULT_UNKNOWN",
                "Google Calendar 등록 결과를 확인할 수 없어 다시 확인해야 합니다.",
                retryable=True,
                unknown=True,
            ) from None

        if response.status_code == 409:
            existing = self.get_event(access_token, event["google_event_id"])
            if existing is not None:
                return {
                    "status": "already_registered",
                    "google_event_id": existing.get("id", event["google_event_id"]),
                    "html_link": existing.get("htmlLink"),
                }
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_RESULT_UNKNOWN",
                "Google Calendar 등록 결과를 확인할 수 없어 다시 확인해야 합니다.",
                retryable=True,
                unknown=True,
            )
        if response.status_code >= 500:
            existing = self.get_event(access_token, event["google_event_id"])
            if existing is not None:
                return {
                    "status": "already_registered",
                    "google_event_id": existing.get("id", event["google_event_id"]),
                    "html_link": existing.get("htmlLink"),
                }
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_RESULT_UNKNOWN",
                "Google Calendar 등록 결과를 확인할 수 없어 다시 확인해야 합니다.",
                retryable=True,
                unknown=True,
            )
        if response.status_code in {401, 403}:
            raise _calendar_access_error(response)
        if response.status_code == 429:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_RATE_LIMITED",
                "Google Calendar 요청 한도에 도달했습니다. 잠시 후 다시 시도해주세요.",
                retryable=True,
            )
        if response.status_code >= 400:
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_EVENT_CREATE_FAILED",
                "Google Calendar에 일정을 추가하지 못했습니다.",
                retryable=False,
            )

        try:
            created_event = response.json()
        except ValueError:
            created_event = None
        if not isinstance(created_event, dict) or not created_event.get("id"):
            raise CalendarGoogleError(
                "GOOGLE_CALENDAR_RESULT_UNKNOWN",
                "Google Calendar 등록 결과를 확인할 수 없어 다시 확인해야 합니다.",
                retryable=True,
                unknown=True,
            )
        return {
            "status": "created",
            "google_event_id": created_event["id"],
            "html_link": created_event.get("htmlLink"),
        }


def _as_date(value: date | datetime | str) -> date:
    """서비스 입력을 종일 이벤트 날짜 객체로 변환한다."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


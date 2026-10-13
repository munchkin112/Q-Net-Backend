"""선택한 회차가 최신이고 같은 회차인지 검증한다."""

import unittest
from contextlib import nullcontext
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

from backend.calendar_registration_service import (
    CalendarRegistrationError,
    validate_selected_schedules,
)
from backend.calendar_schemas import CalendarRegisterRequest
from backend import calendar_registration_service


class CalendarScheduleValidationTests(unittest.TestCase):
    def setUp(self):
        self.certificate_id = uuid4()
        self.written_id = uuid4()
        self.practical_id = uuid4()
        self.version = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
        self.request = CalendarRegisterRequest(
            certificate_id=self.certificate_id,
            schedule_ids=[self.written_id, self.practical_id],
            schedule_versions={
                self.written_id: self.version,
                self.practical_id: self.version,
            },
            event_types=["written_exam", "practical_exam"],
        )
        self.schedules = [
            {
                "id": self.written_id,
                "certificate_id": self.certificate_id,
                "year": 2026,
                "round_key": "regular-1",
                "round_label": "정기 기사 1회",
                "phase": "written",
                "updated_at": self.version,
            },
            {
                "id": self.practical_id,
                "certificate_id": self.certificate_id,
                "year": 2026,
                "round_key": "regular-1",
                "round_label": "정기 기사 1회",
                "phase": "practical",
                "updated_at": self.version,
            },
        ]

    def test_accepts_multiple_phases_from_the_same_round(self):
        result = validate_selected_schedules(self.request, self.schedules)

        self.assertEqual(result, (2026, "regular-1", "정기 기사 1회"))

    def test_rejects_stale_schedule_version(self):
        changed_schedules = [dict(self.schedules[0]), dict(self.schedules[1])]
        changed_schedules[0]["updated_at"] = datetime(2026, 10, 9, tzinfo=timezone.utc)

        with self.assertRaises(CalendarRegistrationError) as context:
            validate_selected_schedules(self.request, changed_schedules)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.code, "SCHEDULE_CHANGED")

    def test_rejects_schedules_from_different_rounds(self):
        changed_schedules = [dict(self.schedules[0]), dict(self.schedules[1])]
        changed_schedules[1]["round_key"] = "regular-2"

        with self.assertRaises(CalendarRegistrationError) as context:
            validate_selected_schedules(self.request, changed_schedules)

        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(context.exception.code, "INVALID_SCHEDULE_SELECTION")

    def test_rejects_contradictory_official_dates(self):
        changed_schedules = [dict(self.schedules[0]), dict(self.schedules[1])]
        changed_schedules[0].update({
            "registration_start": date(2026, 2, 3),
            "registration_end": date(2026, 2, 4),
            "exam_start": date(2026, 2, 1),
            "exam_end": date(2026, 2, 2),
            "result_date": date(2026, 2, 12),
        })

        with self.assertRaises(CalendarRegistrationError) as context:
            validate_selected_schedules(self.request, changed_schedules)

        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(context.exception.code, "INVALID_SCHEDULE")

    def test_registration_calls_google_only_for_selected_event_types(self):
        connection_id = uuid4()
        registration_id = uuid4()
        schedule = {
            **self.schedules[0],
            "certificate_name": "정보처리기사",
            "registration_start": None,
            "registration_end": None,
            "registration_periods": [],
            "exam_start": datetime(2026, 2, 1).date(),
            "exam_end": datetime(2026, 2, 2).date(),
            "result_date": datetime(2026, 2, 12).date(),
            "source_url": "https://www.q-net.or.kr/exam/written",
        }
        request = CalendarRegisterRequest(
            certificate_id=self.certificate_id,
            schedule_ids=[self.written_id],
            schedule_versions={self.written_id: self.version},
            event_types=["written_exam"],
        )
        registration = {"id": registration_id, "certificate_id": self.certificate_id}
        google_event_id = "a" * 64
        saved_event = {
            "id": uuid4(),
            "registration_id": registration_id,
            "google_event_id": google_event_id,
            "html_link": None,
            "sync_status": "pending",
            "retryable": False,
            "schedule_version": self.version,
        }
        updated_event = {
            **saved_event,
            "sync_status": "created",
            "html_link": "https://calendar.google.com/event",
        }
        connection = Mock()
        google_client = Mock()
        google_client.refresh_access_token.return_value = "access-token"
        google_client.ensure_event.return_value = {
            "status": "created",
            "google_event_id": google_event_id,
            "html_link": "https://calendar.google.com/event",
        }

        with patch.object(calendar_registration_service, "database_connection", return_value=nullcontext(connection)), \
             patch.object(calendar_registration_service.calendar_repository, "get_calendar_registration", return_value=None), \
             patch.object(calendar_registration_service.calendar_repository, "list_schedules_for_calendar_registration", return_value=[schedule]), \
             patch.object(calendar_registration_service, "get_calendar_connection_credential", return_value=("refresh-token", "calendar-scope")), \
             patch.object(calendar_registration_service, "GoogleCalendarClient", return_value=google_client), \
             patch.object(calendar_registration_service.calendar_repository, "create_calendar_registration", return_value=(registration, True)) as create_registration, \
             patch.object(calendar_registration_service.calendar_repository, "get_calendar_event", return_value=saved_event), \
             patch.object(calendar_registration_service.calendar_repository, "update_calendar_event_result", return_value=updated_event), \
             patch.object(calendar_registration_service.calendar_repository, "update_calendar_registration_result"):
            result = calendar_registration_service.register_calendar_events(
                connection_id, request, uuid4()
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual([item["event_type"] for item in result["items"]], ["written_exam"])
        persisted_events = create_registration.call_args.args[9]
        self.assertEqual([event["event_type"] for event in persisted_events], ["written_exam"])
        google_client.ensure_event.assert_called_once()

    def test_retry_uses_request_certificate_without_missing_registration_column(self):
        connection_id = uuid4()
        connection = Mock()
        registration = {
            "id": uuid4(),
            "request_hash": calendar_registration_service.create_calendar_request_hash(self.request),
            "request_events": [{"schedule_id": str(self.written_id)}],
            "excluded_items": [],
            "response": {"items": [{"status": "unknown", "retryable": True}]},
        }
        expected = {"status": "completed", "items": []}
        with patch.object(calendar_registration_service, "database_connection", return_value=nullcontext(connection)), \
             patch.object(calendar_registration_service.calendar_repository, "get_calendar_registration", return_value=registration), \
             patch.object(calendar_registration_service.calendar_repository, "create_calendar_registration") as create, \
             patch.object(calendar_registration_service, "_load_google_access_token", return_value="access-token"), \
             patch.object(calendar_registration_service, "_process_registration", return_value=expected) as process:
            result = calendar_registration_service.register_calendar_events(connection_id, self.request, uuid4())
        self.assertEqual(result, expected)
        self.assertEqual(process.call_args.args[-1], self.certificate_id)
        create.assert_not_called()

    def test_same_idempotency_key_with_different_payload_is_rejected(self):
        connection_id = uuid4()
        connection = Mock()

        with patch.object(calendar_registration_service, "database_connection", return_value=nullcontext(connection)), \
             patch.object(calendar_registration_service.calendar_repository, "get_calendar_registration", return_value={"request_hash": "0" * 64}):
            with self.assertRaises(CalendarRegistrationError) as context:
                calendar_registration_service.register_calendar_events(
                    connection_id, self.request, uuid4()
                )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.code, "IDEMPOTENCY_CONFLICT")


if __name__ == "__main__":
    unittest.main()


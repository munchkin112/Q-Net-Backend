"""Calendar 전용 연결을 사용하는 등록 API 계약을 확인한다."""

import unittest
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.calendar_router import create_calendar_router
from backend.calendar_schemas import CalendarRegisterRequest


CONNECTION_ID = UUID("11111111-1111-4111-8111-111111111111")
CERTIFICATE_ID = UUID("22222222-2222-4222-8222-222222222222")
SCHEDULE_ID = UUID("33333333-3333-4333-8333-333333333333")
SCHEDULE_VERSION = "2026-10-08T06:00:00Z"


class CalendarRegisterRequestTests(unittest.TestCase):
    def test_request_accepts_only_user_selected_event_types(self):
        request = CalendarRegisterRequest.model_validate({
            "certificate_id": str(CERTIFICATE_ID),
            "schedule_ids": [str(SCHEDULE_ID)],
            "schedule_versions": {str(SCHEDULE_ID): SCHEDULE_VERSION},
            "event_types": ["written_exam"],
        })

        self.assertEqual(request.event_types, ["written_exam"])
        self.assertEqual(request.schedule_ids, [SCHEDULE_ID])

    def test_request_rejects_empty_or_repeated_selections(self):
        base = {
            "certificate_id": str(CERTIFICATE_ID),
            "schedule_ids": [str(SCHEDULE_ID)],
            "schedule_versions": {str(SCHEDULE_ID): SCHEDULE_VERSION},
        }

        with self.assertRaises(ValueError):
            CalendarRegisterRequest.model_validate({**base, "event_types": []})
        with self.assertRaises(ValueError):
            CalendarRegisterRequest.model_validate({**base, "event_types": ["result", "result"]})


class CalendarRouterTests(unittest.TestCase):
    def test_route_uses_calendar_connection_not_app_login(self):
        captured = {}

        def register(connection_id, request, idempotency_key):
            captured["connection_id"] = connection_id
            captured["event_types"] = request.event_types
            captured["idempotency_key"] = idempotency_key
            return {
                "registration_id": str(idempotency_key),
                "status": "completed",
                "items": [],
                "excluded_items": [],
                "message": "선택한 일정을 등록했습니다.",
            }

        app = FastAPI()
        app.include_router(create_calendar_router(
            current_calendar_connection_dependency=lambda: CONNECTION_ID,
            register_events=register,
        ))
        client = TestClient(app)
        idempotency_key = "44444444-4444-4444-8444-444444444444"

        response = client.post(
            "/calendar/register",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "certificate_id": str(CERTIFICATE_ID),
                "schedule_ids": [str(SCHEDULE_ID)],
                "schedule_versions": {str(SCHEDULE_ID): SCHEDULE_VERSION},
                "event_types": ["written_exam"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["connection_id"], CONNECTION_ID)
        self.assertEqual(captured["event_types"], ["written_exam"])
        self.assertEqual(captured["idempotency_key"], UUID(idempotency_key))

    def test_calendar_register_without_connection_returns_401(self):
        app = FastAPI()
        app.include_router(create_calendar_router())
        client = TestClient(app)

        response = client.post(
            "/calendar/register",
            headers={"Idempotency-Key": "44444444-4444-4444-8444-444444444444"},
            json={
                "certificate_id": str(CERTIFICATE_ID),
                "schedule_ids": [str(SCHEDULE_ID)],
                "schedule_versions": {str(SCHEDULE_ID): SCHEDULE_VERSION},
                "event_types": ["written_exam"],
            },
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()


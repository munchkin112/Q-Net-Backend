"""Calendar 등록 API의 입력 검증과 사용자 선택 전달을 확인한다."""

import unittest
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.calendar_router import create_calendar_router
from backend.calendar_schemas import CalendarRegisterRequest


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
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
    def test_route_passes_authenticated_user_selection_and_idempotency_key(self):
        captured = {}

        def register(user_id, request, idempotency_key):
            captured["user_id"] = user_id
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
            current_user_dependency=lambda: SimpleNamespace(id=USER_ID),
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
        self.assertEqual(captured["user_id"], USER_ID)
        self.assertEqual(captured["event_types"], ["written_exam"])
        self.assertEqual(captured["idempotency_key"], UUID(idempotency_key))


if __name__ == "__main__":
    unittest.main()


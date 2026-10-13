"""Google Calendar API의 안전한 재시도와 종일 이벤트 날짜를 검증한다."""

import json
import os
import unittest
from datetime import date
from collections import deque
from unittest.mock import patch

import httpx

from backend.calendar_google import CalendarGoogleError, GoogleCalendarClient


class GoogleCalendarClientTests(unittest.TestCase):
    def test_disabled_api_is_not_reported_as_missing_user_permission(self):
        body = {"error": {"errors": [{"reason": "accessNotConfigured"}], "details": [{"reason": "SERVICE_DISABLED"}]}}
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403, json=body))) as client:
            with self.assertRaises(CalendarGoogleError) as caught:
                GoogleCalendarClient(client).get_event("test-access-token", "a" * 64)
        self.assertEqual(caught.exception.code, "GOOGLE_CALENDAR_API_DISABLED")
        self.assertFalse(caught.exception.permission_required)
        self.assertTrue(caught.exception.retryable)

    def test_expired_access_token_requires_calendar_reconnection(self):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            with self.assertRaises(CalendarGoogleError) as caught:
                GoogleCalendarClient(client).get_event("test-access-token", "a" * 64)
        self.assertEqual(caught.exception.code, "GOOGLE_CALENDAR_PERMISSION_DENIED")
        self.assertTrue(caught.exception.permission_required)


    def test_create_event_uses_selected_event_and_exclusive_google_end_date(self):
        requests = []

        def handle_request(request):
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(404)
            return httpx.Response(200, json={"id": "a" * 32, "htmlLink": "https://calendar.google.com/event"})

        transport = httpx.MockTransport(handle_request)
        with httpx.Client(transport=transport) as http_client:
            google = GoogleCalendarClient(http_client)
            result = google.ensure_event("access-token", {
                "google_event_id": "a" * 32,
                "title": "정보처리기사 정기 기사 1회 필기시험",
                "description": "공식 출처: https://www.q-net.or.kr",
                "starts_on": date(2026, 2, 1),
                "ends_on": date(2026, 2, 2),
            })

        self.assertEqual(result["status"], "created")
        self.assertEqual(requests[1].url.path, "/calendar/v3/calendars/primary/events")
        body = json.loads(requests[1].content.decode("utf-8"))
        self.assertEqual(body["start"], {"date": "2026-02-01"})
        self.assertEqual(body["end"], {"date": "2026-02-03"})

    def test_existing_event_is_not_inserted_again(self):
        calls = []

        def handle_request(request):
            calls.append(request.method)
            return httpx.Response(200, json={"id": "b" * 32, "htmlLink": "https://calendar.google.com/event"})

        with httpx.Client(transport=httpx.MockTransport(handle_request)) as http_client:
            result = GoogleCalendarClient(http_client).ensure_event("access-token", {
                "google_event_id": "b" * 32,
                "title": "일정",
                "description": "출처",
                "starts_on": date(2026, 2, 1),
                "ends_on": date(2026, 2, 1),
            })

        self.assertEqual(result["status"], "already_registered")
        self.assertEqual(calls, ["GET"])

    def test_malformed_existing_event_response_does_not_claim_duplicate_success(self):
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"summary": "missing id"}))
        ) as http_client:
            with self.assertRaises(CalendarGoogleError):
                GoogleCalendarClient(http_client).ensure_event("access-token", {
                    "google_event_id": "c" * 64,
                    "title": "일정",
                    "description": "출처",
                    "starts_on": date(2026, 2, 1),
                    "ends_on": date(2026, 2, 1),
                })

    def test_conflict_without_visible_event_is_retryable_unknown(self):
        responses = deque([
            httpx.Response(404),
            httpx.Response(409),
            httpx.Response(404),
        ])

        with httpx.Client(
            transport=httpx.MockTransport(lambda request: responses.popleft())
        ) as http_client:
            with self.assertRaises(CalendarGoogleError) as context:
                GoogleCalendarClient(http_client).ensure_event("access-token", {
                    "google_event_id": "d" * 64,
                    "title": "일정",
                    "description": "출처",
                    "starts_on": date(2026, 2, 1),
                    "ends_on": date(2026, 2, 1),
                })

        self.assertTrue(context.exception.unknown)
        self.assertTrue(context.exception.retryable)
        self.assertEqual(context.exception.code, "GOOGLE_CALENDAR_RESULT_UNKNOWN")

    def test_refresh_access_token_uses_server_stored_refresh_token(self):
        requests = []

        def handle_request(request):
            requests.append(request)
            return httpx.Response(200, json={"access_token": "short-lived-access-token"})

        environment = {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REDIRECT_URI": "http://localhost/callback",
        }
        with patch.dict(os.environ, environment):
            with httpx.Client(transport=httpx.MockTransport(handle_request)) as http_client:
                token = GoogleCalendarClient(http_client).refresh_access_token("stored-refresh-token")

        self.assertEqual(token, "short-lived-access-token")
        body = requests[0].content.decode("utf-8")
        self.assertIn("refresh_token=stored-refresh-token", body)
        self.assertNotIn("short-lived-access-token", body)


if __name__ == "__main__":
    unittest.main()


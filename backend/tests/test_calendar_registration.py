"""선택한 Calendar 항목만 공식 일정에서 만드는 동작을 검증한다."""

import json
import unittest
from datetime import date
from uuid import uuid4

from backend.calendar_service import build_selected_calendar_events


class CalendarEventBuilderTests(unittest.TestCase):
    def setUp(self):
        self.certificate_id = uuid4()
        self.written_schedule_id = uuid4()
        self.practical_schedule_id = uuid4()
        self.schedules = [
            {
                "id": self.written_schedule_id,
                "certificate_id": self.certificate_id,
                "year": 2026,
                "round_key": "regular-1",
                "round_label": "정기 기사 1회",
                "phase": "written",
                "registration_start": date(2026, 1, 5),
                "registration_end": date(2026, 1, 8),
                "registration_periods": [
                    {"starts_on": "2026-01-05", "ends_on": "2026-01-08"},
                    {"starts_on": "2026-01-20", "ends_on": "2026-01-21"},
                ],
                "exam_start": date(2026, 2, 1),
                "exam_end": date(2026, 2, 2),
                "result_date": date(2026, 2, 12),
                "source_url": "https://www.q-net.or.kr/exam/written",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "certificate_name": "정보처리기사",
            },
            {
                "id": self.practical_schedule_id,
                "certificate_id": self.certificate_id,
                "year": 2026,
                "round_key": "regular-1",
                "round_label": "정기 기사 1회",
                "phase": "practical",
                "registration_start": date(2026, 2, 15),
                "registration_end": date(2026, 2, 18),
                "registration_periods": [],
                "exam_start": date(2026, 3, 1),
                "exam_end": date(2026, 3, 5),
                "result_date": date(2026, 3, 15),
                "source_url": "https://www.q-net.or.kr/exam/practical",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "certificate_name": "정보처리기사",
            },
        ]

    def test_only_user_selected_event_type_is_created(self):
        events, excluded = build_selected_calendar_events(
            self.schedules,
            ["written_exam"],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "written_exam")
        self.assertEqual(events[0]["schedule_id"], self.written_schedule_id)
        self.assertEqual(events[0]["starts_on"], date(2026, 2, 1))
        self.assertEqual(events[0]["ends_on"], date(2026, 2, 2))
        self.assertEqual(excluded, [])

    def test_selected_registration_creates_each_actual_period_without_gap(self):
        events, excluded = build_selected_calendar_events(
            [self.schedules[0]],
            ["registration"],
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            [(event["starts_on"], event["ends_on"]) for event in events],
            [
                (date(2026, 1, 5), date(2026, 1, 8)),
                (date(2026, 1, 20), date(2026, 1, 21)),
            ],
        )
        self.assertEqual(excluded, [])

    def test_mixed_validity_reports_each_invalid_registration_period(self):
        schedule = {
            **self.schedules[0],
            "registration_periods": [
                {"starts_on": "2026-01-05", "ends_on": "2026-01-08"},
                {"starts_on": "2026-01-21", "ends_on": "2026-01-20"},
                {
                    "starts_on": "2026-01-25",
                    "ends_on": "2026-01-26",
                    "source_url": "not-an-official-url",
                },
                {"starts_on": "not-a-date", "ends_on": "2026-01-28"},
            ],
        }

        events, excluded = build_selected_calendar_events(
            [schedule],
            ["registration"],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["starts_on"], date(2026, 1, 5))
        self.assertEqual(len(excluded), 3)
        self.assertEqual([item["event_type"] for item in excluded], ["registration"] * 3)
        self.assertEqual([item["schedule_id"] for item in excluded], [str(self.written_schedule_id)] * 3)
        self.assertEqual([item["period_index"] for item in excluded], [2, 3, 4])
        self.assertIn("종료일", excluded[0]["reason"])
        self.assertIn("공식 출처", excluded[1]["reason"])
        self.assertIn("시작일", excluded[2]["reason"])
        json.dumps(excluded)

    def test_missing_registration_period_reports_the_schedule_when_other_phase_is_valid(self):
        schedule_without_periods = {
            **self.schedules[1],
            "registration_start": None,
            "registration_end": None,
        }

        events, excluded = build_selected_calendar_events(
            [self.schedules[0], schedule_without_periods],
            ["registration"],
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["event_type"], "registration")
        self.assertEqual(excluded[0]["schedule_id"], str(self.practical_schedule_id))
        self.assertIsNone(excluded[0]["period_index"])
        json.dumps(excluded)

    def test_available_selection_is_created_and_missing_selection_is_reported(self):
        events, excluded = build_selected_calendar_events(
            [self.schedules[0]],
            ["practical_exam", "result"],
        )

        self.assertEqual([event["event_type"] for event in events], ["result"])
        self.assertEqual([item["event_type"] for item in excluded], ["practical_exam"])


if __name__ == "__main__":
    unittest.main()


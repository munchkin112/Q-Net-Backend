"""Calendar 저장소가 SQL 매개변수와 외부 호출 분리를 지키는지 확인한다."""

import unittest
from unittest.mock import Mock
from uuid import uuid4

from backend.db.calendar_repository import list_schedules_for_calendar_registration


class CalendarRepositoryTests(unittest.TestCase):
    def test_schedule_lookup_is_limited_to_requested_certificate_and_ids(self):
        connection = Mock()
        expected_rows = [{"id": uuid4()}]
        connection.execute.return_value.fetchall.return_value = expected_rows
        certificate_id = uuid4()
        schedule_ids = [uuid4()]

        result = list_schedules_for_calendar_registration(
            connection,
            certificate_id,
            schedule_ids,
        )

        self.assertEqual(result, expected_rows)
        query, parameters = connection.execute.call_args.args
        self.assertIn("schedules.certificate_id = %s AND schedules.id = ANY(%s)", query)
        self.assertEqual(parameters, (certificate_id, schedule_ids))


if __name__ == "__main__":
    unittest.main()


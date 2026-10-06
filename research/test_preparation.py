"""사전 수집의 재시도와 전문자격 날짜 처리에서 중요한 경계를 확인한다."""

from unittest import TestCase, main
from unittest.mock import patch

from research.collect_preparation import collect_one
from research.prepare_data import prepare_professional_schedules


def schedule_source() -> dict:
    """시험 연도 다음 해까지 합격자 조회가 가능한 공식 형식의 표본이다."""
    return {"kind": "schedules", "code": "08", "status": "fetched",
            "source_url": "http://openapi.q-net.or.kr/example", "params": {"seriesCd": "08"},
            "retrieved_at": "2026-10-06T09:00:00+09:00", "response_file": "responses/example.txt",
            "items": [{"description": "2026년도 37회 1차", "examregstartdt": "20260803",
                       "examregenddt": "20260807", "examstartdt": "20261031",
                       "examenddt": "20261031", "passstartdt": "20261202", "passenddt": "20270131"}]}


class PreparationTests(TestCase):
    def test_next_year_display_end_preserves_first_phase(self):
        rows, issues = prepare_professional_schedules([schedule_source()])
        self.assertFalse(issues)
        self.assertEqual(rows[0]["phase"], "first")
        self.assertEqual(rows[0]["result_display_end"], "2027-01-31")
        self.assertNotIn("certificate_id", rows[0])

    def test_invalid_dates_are_retained_as_review_issues(self):
        source = schedule_source()
        source["items"][0]["examregenddt"] = "20261101"
        rows, issues = prepare_professional_schedules([source])
        self.assertFalse(rows)
        self.assertEqual(issues[0]["raw_item"]["examregenddt"], "20261101")

    def test_duplicate_series_stage_does_not_make_two_candidates(self):
        source = schedule_source()
        source["items"].append(dict(source["items"][0]))
        rows, issues = prepare_professional_schedules([source])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(issues), 1)

    def test_provider_error_retries_once_and_keeps_both_attempts(self):
        record = {"http_status": 200, "retrieved_at": "2026-10-06T09:00:00+09:00",
                  "response_file": "responses/test.txt", "byte_count": 200}
        error = '<response><header><resultCode>99</resultCode></header><body/></response>'
        with patch("research.collect_preparation.fetch", return_value=(record, error)) as fetch:
            with patch("research.collect_preparation.time.sleep"):
                result = collect_one("schedules", "08")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["attempts"]), 2)

    def test_empty_success_is_not_retried(self):
        record = {"http_status": 200, "retrieved_at": "2026-10-06T09:00:00+09:00",
                  "response_file": "responses/test.txt", "byte_count": 200}
        body = '<response><header><resultCode>00</resultCode></header><body><items/></body></response>'
        with patch("research.collect_preparation.fetch", return_value=(record, body)) as fetch:
            result = collect_one("details", "9630")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["status"], "empty")


if __name__ == "__main__":
    main()

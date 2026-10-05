"""실제 공식 응답과 모의 HTTP 오류로 변환·재시도를 검증한다."""

from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from pydantic import ValidationError

from backend.official_api import OfficialAPIError, parse_xml_items, request_items
from backend.official_data import normalize_catalog, normalize_technical_schedules, parse_official_date
from backend.sync_official import prepare_official_data


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
SOURCE = "https://www.q-net.or.kr/"
EMPTY_XML = "<response><header><resultCode>00</resultCode></header><body><items/></body></response>"


def real_schedule_items() -> list[dict]:
    """조사 당시 확보한 정보처리기사 XML 응답을 읽는다."""
    text = (ROOT / "research/responses/api_operation_7199_1320.txt").read_text(encoding="utf-8")
    return parse_xml_items(text)


class NormalizationTests(unittest.TestCase):
    def test_catalog_count_and_leading_zero(self):
        text = (ROOT / "research/responses/certificate_list.txt").read_text(encoding="utf-8")
        catalog = normalize_catalog(parse_xml_items(text), SOURCE, NOW)
        self.assertEqual(len(catalog), 613)
        self.assertEqual(catalog[0].qnet_code, "0752")

    def test_three_rounds_become_six_phases(self):
        schedules = normalize_technical_schedules(real_schedule_items(), uuid4(), "정보처리기사", SOURCE, NOW)
        self.assertEqual(len(schedules), 6)
        self.assertEqual(len({row.round_key for row in schedules}), 3)
        self.assertEqual({row.phase for row in schedules}, {"written", "practical"})
        practical = schedules[-1]
        self.assertEqual(practical.exam_start.isoformat(), "2026-10-24")
        self.assertEqual(practical.exam_end.isoformat(), "2026-11-13")
        self.assertEqual(practical.result_date.isoformat(), "2026-12-18")
        self.assertEqual(practical.result_display_end.isoformat(), "2027-02-17")

    def test_wrong_certificate_name(self):
        with self.assertRaises(ValueError):
            normalize_technical_schedules(real_schedule_items(), uuid4(), "산업안전기사", SOURCE, NOW)

    def test_invalid_date_and_invalid_order(self):
        items = real_schedule_items()
        items[0]["docregenddt"] = "20260230"
        with self.assertRaises(ValueError):
            normalize_technical_schedules(items, uuid4(), "정보처리기사", SOURCE, NOW)
        items[0]["docregenddt"] = "20260304"
        with self.assertRaises(ValidationError):
            normalize_technical_schedules(items, uuid4(), "정보처리기사", SOURCE, NOW)

    def test_empty_date_is_not_invented(self):
        self.assertIsNone(parse_official_date(""))
        self.assertIsNone(parse_official_date(None))

    def test_bad_date_format(self):
        with self.assertRaises(ValueError):
            parse_official_date("2026-10-24")

    def test_duplicate_catalog_rejected(self):
        item = {"jmcd": "1320", "jmfldnm": "정보처리기사", "qualgbcd": "T"}
        with self.assertRaises(ValueError):
            normalize_catalog([item, item], SOURCE, NOW)

    def test_missing_catalog_name_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_catalog([{"jmcd": "1320", "qualgbcd": "T"}], SOURCE, NOW)

    def test_duplicate_phase_rejected(self):
        items = real_schedule_items()
        with self.assertRaises(ValueError):
            normalize_technical_schedules([items[0], items[0]], uuid4(), "정보처리기사", SOURCE, NOW)

    def test_year_not_guessed(self):
        items = real_schedule_items()
        items[0]["implplannm"] = "정기 기사 1회"
        with self.assertRaises(ValueError):
            normalize_technical_schedules(items, uuid4(), "정보처리기사", SOURCE, NOW)

    def test_empty_schedule_is_normal(self):
        self.assertEqual(normalize_technical_schedules([], uuid4(), "정보처리기사", SOURCE, NOW), [])

    def test_snapshot_preserves_original_time_without_db(self):
        with patch("backend.sync_official.database_connection") as connect:
            prepared = prepare_official_data("1320")
        connect.assert_not_called()
        self.assertEqual(prepared["selected"].last_synced_at.isoformat(), "2026-10-05T14:04:29.300932+09:00")
        self.assertEqual(len(prepared["schedules"]), 6)
        self.assertEqual(prepared["mode"], "snapshot")

    def test_professional_schedule_not_misinterpreted(self):
        with self.assertRaises(ValueError):
            prepare_official_data("9630")


class HTTPTests(unittest.TestCase):
    def request_with_responses(self, responses: list) -> tuple[dict, int]:
        """지정한 모의 응답을 차례대로 돌려주고 실제 호출 횟수를 확인한다."""
        calls = []
        def handler(request):
            calls.append(request)
            value = responses[len(calls) - 1]
            if isinstance(value, Exception):
                raise value
            return value
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = request_items(client, SOURCE)
        return result, len(calls)

    def test_empty_result_not_retried(self):
        result, calls = self.request_with_responses([httpx.Response(200, text=EMPTY_XML)])
        self.assertEqual(calls, 1)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["retry_count"], 0)

    def test_server_error_retried_once(self):
        result, calls = self.request_with_responses([httpx.Response(503), httpx.Response(200, text=EMPTY_XML)])
        self.assertEqual(calls, 2)
        self.assertEqual(result["retry_count"], 1)

    def test_provider_error_inside_http_200(self):
        failure = "<response><header><resultCode>99</resultCode></header></response>"
        result, calls = self.request_with_responses([httpx.Response(200, text=failure), httpx.Response(200, text=EMPTY_XML)])
        self.assertEqual(calls, 2)
        self.assertEqual(result["retry_count"], 1)

    def test_timeout_stops_after_two_calls(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("timeout", request=request)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(OfficialAPIError) as caught:
                request_items(client, SOURCE)
        self.assertEqual(len(calls), 2)
        self.assertEqual(caught.exception.code, "timeout")
        self.assertEqual(caught.exception.retry_count, 1)

    def test_auth_error_not_retried(self):
        with self.assertRaises(OfficialAPIError) as caught:
            self.request_with_responses([httpx.Response(401)])
        self.assertEqual(caught.exception.retry_count, 0)

    def test_invalid_xml_not_retried(self):
        with self.assertRaises(OfficialAPIError) as caught:
            self.request_with_responses([httpx.Response(200, text="<html>error</html>")])
        self.assertEqual(caught.exception.retry_count, 0)

    def test_missing_body_is_not_empty_success(self):
        with self.assertRaises(OfficialAPIError):
            parse_xml_items("<response><header><resultCode>00</resultCode></header></response>")

    def test_xml_entity_rejected(self):
        with self.assertRaises(OfficialAPIError):
            parse_xml_items('<!DOCTYPE x [<!ENTITY secret "value">]><response/>')

    def test_oversized_response(self):
        with patch("backend.official_api.MAX_RESPONSE_BYTES", 10):
            with self.assertRaises(OfficialAPIError) as caught:
                self.request_with_responses([httpx.Response(200, text=EMPTY_XML)])
        self.assertEqual(caught.exception.code, "response_too_large")


if __name__ == "__main__":
    unittest.main()

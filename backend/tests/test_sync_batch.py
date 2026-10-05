"""일괄 수집에서 일부 실패가 나도 다른 종목·작업이 계속되는지 검증한다."""

from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg

from backend import sync_batch
from backend.official_api import OfficialAPIError


def certificate(code="1320") -> dict:
    return {"id": uuid4(), "qnet_code": code, "name": "검증 종목", "category": "T"}


class BatchTests(unittest.TestCase):
    def test_resume_does_not_fetch_completed_certificate_again(self):
        first, second = certificate(), certificate('1431')
        catalog = {'1320': first, '1431': second}
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'resume.json'
            previous = {'requested_codes': ['1320', '1431'], 'only': 'details', 'apply_requested': False,
                        'results': [{'qnet_code': '1320', 'details': {'status': 'validated'}, 'schedules': {'status': 'not_requested'}}]}
            output.write_text(json.dumps(previous), encoding='utf-8')
            with patch.object(sync_batch, 'collect_details', return_value={'status': 'validated'}) as collect:
                with patch.object(sync_batch.time, 'sleep'):
                    result = sync_batch.run_batch(['1320', '1431'], False, 'details', 1, output, catalog, resume=True)
            collect.assert_called_once_with(second, False, 1)
            self.assertEqual(len(result['results']), 2)
            with self.assertRaises(ValueError):
                sync_batch.run_batch(['1320'], False, 'details', 1, output, catalog, resume=True)

    def test_fee_failure_preserves_successful_detail_source(self):
        response = {'items': [], 'source_url': 'https://www.q-net.or.kr/',
                    'retrieved_at': datetime(2026, 10, 5, tzinfo=timezone.utc), 'retry_count': 0}
        with patch.object(sync_batch, 'fetch_exam_information', return_value=response):
            with patch.object(sync_batch, 'fetch_exam_fees', side_effect=OfficialAPIError('timeout', '시간초과', True)):
                with patch.object(sync_batch.time, 'sleep'):
                    result = sync_batch.collect_details(certificate(), False, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['detail_response']['retrieved_at'], response['retrieved_at'].isoformat())

    def test_offline_reprocessing_uses_original_timestamp_without_external_calls(self):
        from backend.tests.test_exam_information import sample_results
        cert = certificate()
        cert['name'] = '정보처리기사'
        detail, fee = sample_results()
        for response in (detail, fee):
            response['retrieved_at'] = response['retrieved_at'].isoformat()
        original = {'requested_codes': ['1320'], 'completed': True, 'results': [
            {'qnet_code': '1320', 'name': cert['name'], 'certificate_id': str(cert['id']),
             'details': {'status': 'incomplete', 'detail_response': detail, 'fee_response': fee}}
        ]}
        with TemporaryDirectory() as directory:
            source, output = Path(directory) / 'raw.json', Path(directory) / 'normalized.json'
            source.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(sync_batch, 'load_technical_catalog', return_value={'1320': cert}):
                with patch.object(sync_batch, 'database_connection', return_value=nullcontext(Mock())):
                    with patch.object(sync_batch, 'fetch_exam_information') as fetch:
                        report = sync_batch.reprocess_details(source, False, output)
            fetch.assert_not_called()
            saved = report['results'][0]['details']
            self.assertEqual(saved['status'], 'validated')
            self.assertEqual(datetime.fromisoformat(saved['information']['subjects']['retrieved_at']),
                             datetime.fromisoformat(detail['retrieved_at']))
            del original['results'][0]['details']['fee_response']
            original['results'][0]['details'].update(status='failed', error_type='provider_error')
            source.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(sync_batch, 'load_technical_catalog', return_value={'1320': cert}):
                with patch.object(sync_batch, 'database_connection', return_value=nullcontext(Mock())):
                    partial = sync_batch.reprocess_details(source, False, output, allow_partial=True)['results'][0]['details']
            self.assertEqual(partial['status'], 'validated_partial')
            self.assertIsNone(partial['information']['fees']['retrieved_at'])
            self.assertEqual(partial['collection_error']['error_type'], 'provider_error')

    def test_unknown_code_does_not_stop_next_certificate_and_duplicate_is_skipped(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with patch.object(sync_batch, "database_connection", return_value=nullcontext(Mock())):
                with patch.object(sync_batch, "get_certificate_by_code", side_effect=[None, certificate()]):
                    with patch.object(sync_batch, "collect_details", return_value={"status": "validated"}) as details:
                        with patch.object(sync_batch.time, "sleep"):
                            report = sync_batch.run_batch(["bad", "1320", "1320"], False, "details", 1, output)
            self.assertEqual(report["summary"]["details"], {"failed": 1, "validated": 1})
            self.assertEqual(details.call_count, 1)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["completed"])
            self.assertFalse(output.with_suffix(".json.tmp").exists())

    def test_failed_details_do_not_stop_schedule_or_next_certificate(self):
        with TemporaryDirectory() as directory:
            with patch.object(sync_batch, "database_connection", return_value=nullcontext(Mock())):
                with patch.object(sync_batch, "get_certificate_by_code", side_effect=[certificate(), certificate("1431")]):
                    with patch.object(sync_batch, "collect_details", side_effect=[{"status": "failed"}, {"status": "saved"}]):
                        with patch.object(sync_batch, "collect_schedules", return_value={"status": "empty"}) as schedules:
                            with patch.object(sync_batch.time, "sleep"):
                                report = sync_batch.run_batch(["1320", "1431"], True, "both", 1, Path(directory) / "result.json")
            self.assertEqual(schedules.call_count, 2)
            self.assertEqual(report["summary"]["details"], {"failed": 1, "saved": 1})
            self.assertEqual(report["summary"]["schedules"], {"empty": 2})

    def test_empty_schedule_never_clears_existing_rows(self):
        response = {"items": [], "source_url": "https://www.q-net.or.kr/", "retrieved_at": datetime.now(timezone.utc), "retry_count": 0}
        with patch.object(sync_batch, "fetch_technical_schedules", return_value=response):
            with patch.object(sync_batch, "database_connection") as connect:
                result = sync_batch.collect_schedules(certificate(), True)
        self.assertEqual(result["status"], "empty")
        connect.assert_not_called()

    def test_timeout_and_db_errors_are_classified_without_secret_details(self):
        error = OfficialAPIError("timeout", "시간초과", True)
        error.retry_count = 1
        with patch.object(sync_batch, "fetch_exam_information", side_effect=error):
            result = sync_batch.collect_details(certificate(), True, 1)
        self.assertEqual(result["error_type"], "timeout")
        self.assertEqual(result["retry_count"], 1)
        safe = sync_batch.error_result(psycopg.OperationalError("secret-password"), "database_save")
        self.assertNotIn("secret-password", str(safe))


if __name__ == "__main__":
    unittest.main()

"""공식 원문 변환과 미확인 정보 처리, 상세 API, 실제 저장 보호를 검증한다."""

from contextlib import nullcontext
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.exam_data import normalize_exam_information, plain_text, parse_fees, split_phases
from backend.exam_schemas import ExamInformationInput, FeesInfo
from backend.main import app
from backend.official_api import parse_xml_items
from backend.services import certificate_detail


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def sample_results() -> tuple[dict, dict]:
    """이전 공식 조사에서 저장한 실제 XML을 테스트 자료로 읽는다."""
    detail = {
        "items": parse_xml_items((ROOT / "research/responses/certificate_information.txt").read_text(encoding="utf-8")),
        "source_url": "http://openapi.q-net.or.kr/api/service/rest/InquiryInformationTradeNTQSVC/getList?jmCd=1320",
        "retrieved_at": NOW,
    }
    fee = {
        "items": parse_xml_items((ROOT / "research/responses/api_operation_7198_1320.txt").read_text(encoding="utf-8")),
        "source_url": "http://openapi.q-net.or.kr/api/service/rest/InquiryTestInformationNTQSVC/getFeeList?jmCd=1320",
        "retrieved_at": NOW,
    }
    return detail, fee


def sample_information(certificate_id=None) -> ExamInformationInput:
    return normalize_exam_information(certificate_id or uuid4(), "정보처리기사", *sample_results())


class ExamInformationTests(unittest.TestCase):
    def test_inline_labels_parentheses_and_joint_labels(self):
        result = split_phases('- 필기 : 40점 이상- 실기(복합형) : 60점 이상')
        self.assertEqual(result['written'], '40점 이상')
        self.assertEqual(result['practical'], '60점 이상')
        result = split_phases('- 필기 및 면접시험 : 60점 이상')
        self.assertEqual(result['written'], result['interview'])
        self.assertIsNone(split_phases('필기 : A\n필기 : B')['written'])
        result = split_phases('필기1. 안전 2. 관리\n실기 : 작업')
        self.assertEqual(result['written'], '1. 안전 2. 관리')
        result = split_phases('필기 : 안전 실기 : 작업')
        self.assertEqual(result['written'], '안전')
        self.assertEqual(result['practical'], '작업')
        result = split_phases('(필기·실기 동일) : 60점 이상')
        self.assertEqual(result['written'], '60점 이상')
        self.assertEqual(result['practical'], '60점 이상')

    def test_interview_and_common_subjects_preserve_explicit_phases(self):
        detail, fee = sample_results()
        acquisition = next(item for item in detail['items'] if item['infogb'] == '취득방법')
        acquisition['contents'] = '시험과목 : 시스템 설계\n검정방법 - 필기 : 논술형 - 면접 : 구술형\n합격기준 - 필기·면접 : 60점 이상'
        result = normalize_exam_information(uuid4(), '정보처리기사', detail, fee)
        self.assertEqual(result.subjects.common, ['시스템 설계'])
        self.assertIsNone(result.subjects.written)
        self.assertEqual(result.subjects.phases, ['written', 'interview'])
        self.assertEqual(result.fees.interview, 22600)
        self.assertIsNone(result.fees.practical)
        self.assertEqual(result.pass_criteria.interview, '60점 이상')

    def test_practical_only_exam_is_not_reported_as_missing_written_exam(self):
        detail, fee = sample_results()
        acquisition = next(item for item in detail['items'] if item['infogb'] == '취득방법')
        acquisition['contents'] = '시험과목 : 석재붙임(필기시험 없음)\n검정방법 : 작업형\n합격기준 : 60점 이상'
        fee['items'][0]['contents'] = ', 2차 : 50200'
        result = normalize_exam_information(uuid4(), '정보처리기사', detail, fee)
        self.assertEqual(result.subjects.phases, ['practical'])
        self.assertEqual(result.subjects.status, 'available')
        self.assertEqual(result.fees.status, 'available')
        self.assertIsNone(result.fees.written)
        acquisition['contents'] = '시험과목 - 실기 : 방수작업\n검정방법 - 실기 : 작업형\n합격기준 - 실기 : 60점 이상'
        result = normalize_exam_information(uuid4(), '정보처리기사', detail, fee)
        self.assertEqual(result.subjects.practical, ['방수작업'])
        self.assertEqual(result.subjects.phases, ['practical'])

    def test_conflicting_and_duplicate_source_labels_remain_unknown(self):
        detail, fee = sample_results()
        acquisition = next(item for item in detail['items'] if item['infogb'] == '취득방법')
        acquisition['contents'] = '시험과목\n필기 : A\n필기 : B\n검정방법\n필기 : 논술형\n면접 : 구술형\n합격기준\n필기·실기 : 60점 이상'
        result = normalize_exam_information(uuid4(), '정보처리기사', detail, fee)
        self.assertEqual(result.subjects.status, 'unavailable')
        self.assertIsNone(result.subjects.common)
        self.assertEqual(result.pass_criteria.status, 'partial')
        self.assertIsNone(result.pass_criteria.interview)
        self.assertIsNone(result.pass_criteria.practical)
        acquisition['contents'] = '시험과목\n필기 : A\n실기 : 작업\n검정방법\n필기 : 객관식\n실기 : 작업형\n합격기준\n필기 : 60점\n면접 : 60점'
        result = normalize_exam_information(uuid4(), '정보처리기사', detail, fee)
        self.assertEqual(result.subjects.phases, ['written', 'practical'])
        self.assertEqual(result.subjects.practical, ['작업'])
        self.assertIsNone(result.pass_criteria.interview)
        self.assertEqual(result.pass_criteria.status, 'partial')

    def test_ten_actual_certificates_subject_counts_and_criteria_boundaries(self):
        import json
        report = json.loads((ROOT / "research/batch_detail_preview.json").read_text(encoding="utf-8"))
        counts = {"1320": 5, "1431": 6, "1150": 5, "1630": 5, "1250": 6,
                  "2290": 3, "2140": 5, "7910": 1, "7780": 3, "6892": 3}
        for row in report["results"]:
            with self.subTest(code=row["qnet_code"]):
                evidence = row["details"]
                source = evidence["information"]
                detail = {"items": evidence["detail_items"], "source_url": source["subjects"]["source_url"],
                          "retrieved_at": datetime.fromisoformat(source["subjects"]["retrieved_at"])}
                fee = {"items": evidence["fee_items"], "source_url": source["fees"]["source_url"],
                       "retrieved_at": datetime.fromisoformat(source["fees"]["retrieved_at"])}
                result = normalize_exam_information(row["certificate_id"], row["name"], detail, fee)
                self.assertEqual(len(result.subjects.written), counts[row["qnet_code"]])
                self.assertNotIn("안전등급", result.pass_criteria.practical)
                self.assertNotIn("작업형 실기시험 기본정보", result.pass_criteria.practical)
                self.assertEqual(result.fees.status, "available")

    def test_actual_response_subjects_criteria_and_fees(self):
        result = sample_information()
        self.assertEqual(result.subjects.written, ["소프트웨어설계", "소프트웨어개발", "데이터베이스구축", "프로그래밍언어활용", "정보시스템구축관리"])
        self.assertEqual(result.subjects.practical, ["정보처리 실무"])
        self.assertIn("과목당 40점 이상", result.pass_criteria.written)
        self.assertIn("평균 60점 이상", result.pass_criteria.written)
        self.assertEqual((result.fees.written, result.fees.practical), (19400, 22600))
        self.assertEqual(result.subjects.retrieved_at, NOW)

    def test_empty_results_are_unknown_not_zero_or_empty_subjects(self):
        detail, fee = sample_results()
        detail["items"], fee["items"] = [], []
        result = normalize_exam_information(uuid4(), "정보처리기사", detail, fee)
        self.assertIsNone(result.subjects.written)
        self.assertIsNone(result.fees.written)
        self.assertEqual(result.fees.status, "unavailable")

    def test_wrong_certificate_is_rejected(self):
        detail, fee = sample_results()
        fee["items"][0]["jmfldnm"] = "다른 자격증"
        with self.assertRaises(ValueError):
            normalize_exam_information(uuid4(), "정보처리기사", detail, fee)

    def test_missing_section_does_not_read_other_sections_as_subjects(self):
        detail, fee = sample_results()
        acquisition = next(item for item in detail["items"] if item["infogb"] == "취득방법")
        acquisition["contents"] = "합격기준\n- 필기 : 60점 이상\n- 실기 : 60점 이상"
        result = normalize_exam_information(uuid4(), "정보처리기사", detail, fee)
        self.assertEqual(result.subjects.status, "unavailable")
        self.assertEqual(result.pass_criteria.status, "available")

    def test_html_becomes_text_and_scripts_are_discarded(self):
        self.assertEqual(plain_text('<p>필기 : A&nbsp;B</p><script>위험</script><style>숨김</style><p>실기 : C</p>'), '필기 : A B\n실기 : C')

    def test_last_numeric_value_is_not_removed(self):
        detail, fee = sample_results()
        acquisition = next(item for item in detail["items"] if item["infogb"] == "취득방법")
        acquisition["contents"] = "합격기준\n- 필기 : 60\n- 실기 : 60"
        result = normalize_exam_information(uuid4(), "정보처리기사", detail, fee)
        self.assertEqual(result.pass_criteria.practical, "60")

    def test_fee_formats_and_invalid_values(self):
        self.assertEqual(parse_fees("필기 : 19,400원, 실기 : 22,600원"), {"written": 19400, "practical": 22600})
        for text in ["1차 : 19,40", "1차 : 19400.5", "1차 : -100", "1차 : 19400원부터", "1차 : 100, 필기 : 200"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_fees(text)["written"])
        self.assertEqual(parse_fees("필기 : 0, 실기 : 200")["written"], 0)

    def test_source_status_and_timezone_are_validated(self):
        with self.assertRaises(ValidationError):
            FeesInfo(source_url="https://www.q-net.or.kr/", retrieved_at=datetime(2026, 10, 5))
        result = sample_information().model_dump()
        result["fees"]["status"] = "unavailable"
        with self.assertRaises(ValidationError):
            ExamInformationInput(**result)

    def test_uncollected_certificate_detail_is_explicit(self):
        identifier = uuid4()
        certificate = {"id": identifier, "qnet_code": "0752", "name": "가스기술사", "category": "T", "career_tags": [], "description": None, "source_url": "https://www.q-net.or.kr/", "last_synced_at": NOW, "updated_at": NOW}
        with patch("backend.services.database_connection", return_value=nullcontext(Mock())):
            with patch("backend.services.get_certificate", return_value=certificate):
                with patch("backend.services.get_exam_information", return_value=None):
                    result = certificate_detail(identifier)
        with patch.dict(os.environ, {"DATABASE_URL": "test-only"}):
            with patch("backend.main.certificate_detail", return_value=result):
                with TestClient(app) as client:
                    response = client.get(f"/certificates/{identifier}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data_status"], "unavailable")
        self.assertIsNone(response.json()["exam_information"]["fees"]["written"])
        self.assertIsNone(response.json()["exam_information"]["retrieved_at"])

    def test_detail_404_and_503(self):
        with TestClient(app) as client:
            with patch.dict(os.environ, {"DATABASE_URL": "test-only"}):
                with patch("backend.main.certificate_detail", return_value=None):
                    self.assertEqual(client.get(f"/certificates/{uuid4()}").status_code, 404)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(client.get(f"/certificates/{uuid4()}").status_code, 503)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "테스트 PostgreSQL 연결 정보 미제공")
class ExamDatabaseTests(unittest.TestCase):
    def test_save_repeat_old_partial_and_rollback(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from backend.db.exam_repository import get_exam_information, save_exam_information

        connection = psycopg.connect(os.environ["TEST_DATABASE_URL"], row_factory=dict_row, connect_timeout=10)
        try:
            schema_name = "test_qnet_" + uuid4().hex
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_name)))
            connection.execute((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
            connection.execute((ROOT / "backend/db/exam_information.sql").read_text(encoding="utf-8"))
            identifier = uuid4()
            connection.execute("INSERT INTO certificates(id, qnet_code, name, category, source_url, last_synced_at) VALUES (%s, '1320', '정보처리기사', 'T', 'https://www.q-net.or.kr/', now())", (identifier,))
            information = sample_information(identifier)
            saved = save_exam_information(connection, information)
            save_exam_information(connection, information)
            self.assertEqual(connection.execute("SELECT count(*) AS count FROM exam_information").fetchone()["count"], 1)
            self.assertEqual(saved["fees"]["written"], 19400)
            old = information.model_dump()
            for field in ("subjects", "pass_criteria", "fees"):
                old[field]["retrieved_at"] = NOW - timedelta(days=1)
            old["fees"]["written"] = 999
            self.assertEqual(save_exam_information(connection, ExamInformationInput(**old))["fees"]["written"], 19400)
            # 새 수수료와 오래된 과목이 섞인 입력도 기존 과목을 덮어쓰지 못한다.
            old["fees"]["retrieved_at"] = NOW + timedelta(days=1)
            self.assertEqual(save_exam_information(connection, ExamInformationInput(**old))["fees"]["written"], 19400)
            partial = information.model_dump()
            partial["subjects"]["written"] = None
            partial["subjects"]["status"] = "partial"
            with self.assertRaises(ValueError):
                save_exam_information(connection, ExamInformationInput(**partial))
            self.assertEqual(get_exam_information(connection, identifier)["subjects"], saved["subjects"])
            # 일부 자료 저장을 허용해도 기존에 확인한 값은 지우지 않는다.
            self.assertEqual(save_exam_information(connection, ExamInformationInput(**partial), allow_partial=True)['subjects'], saved['subjects'])
            second_id = uuid4()
            connection.execute("INSERT INTO certificates(id, qnet_code, name, category, source_url, last_synced_at) VALUES (%s, 'test-partial', '부분 검증', 'T', 'https://www.q-net.or.kr/', now())", (second_id,))
            partial['certificate_id'] = second_id
            saved_partial = save_exam_information(connection, ExamInformationInput(**partial), allow_partial=True)
            self.assertIsNone(saved_partial['subjects']['written'])
            self.assertEqual(saved_partial['subjects']['status'], 'partial')
            upgraded = sample_information(second_id)
            self.assertEqual(save_exam_information(connection, upgraded, allow_partial=True)['subjects']['status'], 'available')
            # API 실패로 출처 시각 자체가 없는 필드도 나중에 정상 응답으로 갱신할 수 있다.
            third_id = uuid4()
            connection.execute("INSERT INTO certificates(id, qnet_code, name, category, source_url, last_synced_at) VALUES (%s, 'test-no-fee', '수수료 미확인', 'T', 'https://www.q-net.or.kr/', now())", (third_id,))
            no_fee = sample_information(third_id).model_dump()
            no_fee['fees'] = FeesInfo().model_dump()
            no_fee['raw_fee_text'] = None
            first = save_exam_information(connection, ExamInformationInput(**no_fee), allow_partial=True)
            self.assertIsNone(first['fees']['retrieved_at'])
            self.assertEqual(save_exam_information(connection, sample_information(third_id), allow_partial=True)['fees']['written'], 19400)
        finally:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    unittest.main()

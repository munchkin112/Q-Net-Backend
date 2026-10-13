"""로그인 없이 추천 요청 본문으로 처리하는 계약을 검증한다."""
import unittest
from copy import deepcopy
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.career_information import build_career_information
from backend.recommendation_router import (
    build_recommendation_response,
    create_recommendation_router,
)
from backend.recommendation_service import RecommendationError


PROFILE = {
    "interest_category_codes": ["20"],
    "education_level": "university",
    "education_status": "graduated",
    "major": None,
    "has_career": False,
    "career_years": None,
}
CERT = "79a6a7a3-5fbc-4b64-80dd-732206f3fb81"
DOC = {
    "document_id": "duties",
    "content": "소프트웨어를 개발한다.",
    "source_url": "https://www.q-net.or.kr/example",
    "retrieved_at": "2026-10-10T00:00:00Z",
}
CONTEXT = {
    "certificate_id": CERT,
    "qnet_code": "1320",
    "name": "정보처리기사",
    "category": "T",
    "summary": "소프트웨어 개발 자격",
    "review_status": "assistant_reviewed_summary_and_roles",
    "related_jobs": [{
        "name": "소프트웨어 개발 담당",
        "source_ids": ["duties"],
        "evidence_anchor": "소프트웨어를 개발한다.",
    }],
    "evidence_documents": [DOC],
}


def result():
    return {
        "selection": {
            "status": "completed",
            "items": [{
                "certificate_id": CERT,
                "reason": "선택한 분야의 개발 업무와 연결됩니다.",
                "profile_factors": [],
                "evidence": [{
                    "document_id": "duties",
                    "quote": "소프트웨어를 개발한다.",
                }],
            }],
        },
        "candidates": [deepcopy(CONTEXT)],
    }


class RecommendationRouterTests(unittest.TestCase):
    def client(self, run=None, context=None):
        app = FastAPI()
        self.run = run or Mock(return_value=result())
        self.context = Mock(return_value=CONTEXT if context is None else context)
        app.include_router(create_recommendation_router(
            run_agent=self.run,
            load_context=self.context,
        ))
        return TestClient(app)

    def test_recommendation_accepts_profile_without_login(self):
        client = self.client()
        response = client.post("/recommendations", json=PROFILE)

        self.assertEqual(response.status_code, 200)
        self.run.assert_called_once_with(PROFILE, ["20"])
        self.assertEqual(response.json()["items"][0]["name"], "정보처리기사")

    def test_recommendation_rejects_missing_or_invalid_profile_before_llm(self):
        client = self.client()
        response = client.post("/recommendations", json={})
        self.assertEqual(response.status_code, 422)
        self.run.assert_not_called()

        response = client.post("/recommendations", json={
            **PROFILE,
            "interest_category_codes": ["20", "19"],
        })
        self.assertEqual(response.status_code, 422)
        self.run.assert_not_called()

    def test_client_cannot_send_user_identity_or_unknown_fields(self):
        response = self.client().post("/recommendations", json={
            **PROFILE,
            "user_id": "11111111-1111-4111-8111-111111111111",
        })
        self.assertEqual(response.status_code, 422)
        self.run.assert_not_called()

    def test_cards_include_common_audience_jobs_sources_and_order(self):
        response = self.client().post("/recommendations", json=PROFILE)
        self.assertEqual(response.status_code, 200)
        card = response.json()["items"][0]
        self.assertEqual(card["position"], 1)
        self.assertIn("관심 있는 분", card["recommended_for"][0]["text"])
        self.assertEqual(card["related_jobs"][0]["name"], "소프트웨어 개발 담당")
        self.assertEqual(card["sources"][0]["source_url"], DOC["source_url"])

    def test_professional_certificate_category_uses_qnet_code_s(self):
        data = result()
        data["candidates"][0]["category"] = "S"
        response = self.client(run=Mock(return_value=data)).post(
            "/recommendations", json=PROFILE
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["category_name"], "국가전문자격")

    def test_no_results_and_failure_are_distinct(self):
        run = Mock(return_value={"selection": {"status": "no_results", "items": []},
                                 "candidates": []})
        response = self.client(run=run).post("/recommendations", json=PROFILE)
        self.assertEqual(response.json()["total_count"], 0)
        response = self.client(
            run=Mock(side_effect=RecommendationError("timeout", "private detail"))
        ).post("/recommendations", json=PROFILE)
        self.assertEqual(response.status_code, 504)
        self.assertNotIn("private detail", response.text)

    def test_career_endpoint_is_public(self):
        response = self.client().get(f"/certificates/{CERT}/career-info")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["certificate_id"], CERT)

    def test_foreign_job_source_rejected(self):
        context = deepcopy(CONTEXT)
        context["related_jobs"][0]["source_ids"] = ["other-certificate"]
        with self.assertRaises(ValueError):
            build_career_information(context)

    def test_missing_job_not_inferred_and_audience_limited(self):
        context = deepcopy(CONTEXT)
        context["related_jobs"] = []
        info = build_career_information(context)
        self.assertEqual(info["related_jobs"], [])
        self.assertEqual(info["recommended_for"], [])
        self.assertEqual(info["status"], "unavailable")

    def test_agent_order_preserved_and_more_than_ten_rejected(self):
        data = result()
        original = deepcopy(data["selection"]["items"][0])
        other = deepcopy(CONTEXT)
        other["certificate_id"] = "d4fc54fd-069f-4e53-92a1-238a40ac6b26"
        other["name"] = "다른 후보"
        data["candidates"].append(other)
        data["selection"]["items"].insert(
            0, {**original, "certificate_id": other["certificate_id"]}
        )
        response = build_recommendation_response(data, PROFILE)
        self.assertEqual(
            [item["certificate_id"] for item in response["items"]],
            [other["certificate_id"], CERT],
        )
        self.assertEqual(response["initial_display_count"], 2)
        data["selection"]["items"] = [original] * 11
        with self.assertRaises(ValueError):
            build_recommendation_response(data, PROFILE)


if __name__ == "__main__":
    unittest.main()


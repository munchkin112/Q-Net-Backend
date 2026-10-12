"""인증 연결 전에도 독립 라우터의 보호·응답 계약을 검증한다."""
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recommendation_router import create_recommendation_router, build_recommendation_response
from backend.career_information import build_career_information
from backend.recommendation_service import RecommendationError

USER = UUID('11111111-1111-4111-8111-111111111111')
CERT = '79a6a7a3-5fbc-4b64-80dd-732206f3fb81'
DOC = {'document_id': 'duties', 'content': '소프트웨어를 개발한다.',
       'source_url': 'https://www.q-net.or.kr/example', 'retrieved_at': '2026-10-10T00:00:00Z'}
CONTEXT = {'certificate_id': CERT, 'qnet_code': '1320', 'name': '정보처리기사', 'category': 'T',
           'summary': '소프트웨어 개발 자격', 'review_status': 'assistant_reviewed_summary_and_roles',
           'related_jobs': [{'name': '소프트웨어 개발 담당', 'source_ids': ['duties'],
                             'evidence_anchor': '소프트웨어를 개발한다.'}], 'evidence_documents': [DOC]}
PROFILE = {'interest_category_codes': ['20'], 'education_level': 'university',
           'education_status': 'graduated', 'major': None, 'has_career': False, 'career_years': None}


def result():
    return {'selection': {'status': 'completed', 'items': [{'certificate_id': CERT,
            'reason': '선택한 분야의 개발 업무와 연결됩니다.', 'profile_factors': [],
            'evidence': [{'document_id': 'duties', 'quote': '소프트웨어를 개발한다.'}]}]},
            'candidates': [deepcopy(CONTEXT)]}


class RecommendationRouterTests(unittest.TestCase):
    def client(self, profile=None, run=None, context=None, configured=True):
        app = FastAPI()
        self.load = Mock(return_value=PROFILE if profile is None else profile)
        self.run = run or Mock(return_value=result())
        if configured:
            router = create_recommendation_router(lambda: USER, self.load, self.run,
                                                  Mock(return_value=CONTEXT if context is None else context))
        else:
            router = create_recommendation_router()
        app.include_router(router)
        return TestClient(app)

    def test_unconfigured_auth_never_accepts_arbitrary_bearer(self):
        client = self.client(configured=False)
        self.assertEqual(client.post('/recommendations', json={}).status_code, 401)
        with patch('backend.auth_dependencies.get_auth_token_settings',
                   side_effect=RuntimeError('auth settings are unavailable')):
            response = client.post('/recommendations', json={},
                                   headers={'Authorization': 'Bearer fake'})
        self.assertEqual(response.status_code, 503)

    def test_cards_include_common_audience_jobs_sources_and_order(self):
        response = self.client().post('/recommendations', json={})
        self.assertEqual(response.status_code, 200)
        card = response.json()['items'][0]
        self.assertEqual(card['position'], 1)
        self.assertIn('관심 있는 분', card['recommended_for'][0]['text'])
        self.assertEqual(card['related_jobs'][0]['name'], '소프트웨어 개발 담당')
        self.assertEqual(card['sources'][0]['source_url'], DOC['source_url'])
        self.load.assert_called_once_with(USER)

    def test_professional_certificate_category_uses_qnet_code_s(self):
        data = result()
        data['candidates'][0]['category'] = 'S'
        response = self.client(run=Mock(return_value=data)).post('/recommendations', json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'][0]['category_name'], '국가전문자격')

    def test_client_cannot_choose_user_or_override_saved_profile(self):
        client = self.client()
        response = client.post('/recommendations', json={'user_id': str(USER), 'profile': PROFILE})
        self.assertEqual(response.status_code, 422)
        self.run.assert_not_called()

    def test_multiple_interests_rejected_before_llm(self):
        response = self.client(profile={**PROFILE, 'interest_category_codes': ['20', '19']}).post('/recommendations', json={})
        self.assertEqual(response.status_code, 422)
        self.run.assert_not_called()

    def test_no_results_and_failure_are_distinct(self):
        run = Mock(return_value={'selection': {'status': 'no_results', 'items': []}, 'candidates': []})
        response = self.client(run=run).post('/recommendations', json={})
        self.assertEqual(response.json()['total_count'], 0)
        response = self.client(run=Mock(side_effect=RecommendationError('timeout', 'secret'))).post('/recommendations', json={})
        self.assertEqual(response.status_code, 504)
        self.assertNotIn('secret', response.text)

    def test_career_endpoint_uses_selected_certificate(self):
        response = self.client().get(f'/certificates/{CERT}/career-info')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['certificate_id'], CERT)

    def test_foreign_job_source_rejected(self):
        context = deepcopy(CONTEXT)
        context['related_jobs'][0]['source_ids'] = ['other-certificate']
        with self.assertRaises(ValueError):
            build_career_information(context)

    def test_missing_job_not_inferred_and_audience_limited(self):
        context = deepcopy(CONTEXT)
        context['related_jobs'] = []
        info = build_career_information(context)
        self.assertEqual(info['related_jobs'], [])
        self.assertEqual(info['recommended_for'], [])
        self.assertEqual(info['status'], 'unavailable')

    def test_agent_order_preserved_and_more_than_ten_rejected(self):
        data = result()
        original = deepcopy(data['selection']['items'][0])
        other = deepcopy(CONTEXT)
        other['certificate_id'] = 'd4fc54fd-069f-4e53-92a1-238a40ac6b26'
        other['name'] = '다른 후보'
        data['candidates'].append(other)
        data['selection']['items'].insert(0, {**original, 'certificate_id': other['certificate_id']})
        response = build_recommendation_response(data, PROFILE)
        self.assertEqual([item['certificate_id'] for item in response['items']], [other['certificate_id'], CERT])
        self.assertEqual(response['initial_display_count'], 2)
        data['selection']['items'] = [original] * 11
        with self.assertRaises(ValueError):
            build_recommendation_response(data, PROFILE)

    def test_missing_certificate_and_invalid_uuid(self):
        self.assertEqual(self.client().get('/certificates/not-a-uuid/career-info').status_code, 422)
        client = self.client()
        unknown = '22222222-2222-4222-8222-222222222222'
        self.assertEqual(client.get(f'/certificates/{unknown}/career-info').status_code, 502)
        app = FastAPI()
        app.include_router(create_recommendation_router(lambda: USER, load_context=lambda certificate_id: None))
        self.assertEqual(TestClient(app).get(f'/certificates/{unknown}/career-info').status_code, 404)

    def test_common_audience_keeps_evidence_scope_and_stops_at_three(self):
        context = deepcopy(CONTEXT)
        context['related_jobs'] = [{**CONTEXT['related_jobs'][0], 'name': f'업무 {index} (공통 직무)'}
                                  for index in range(4)]
        context['evidence_documents'][0]['evidence_scope'] = 'family_common'
        info = build_career_information(context)
        self.assertEqual(len(info['recommended_for']), 3)
        self.assertEqual(len(info['related_jobs']), 4)
        self.assertEqual(info['sources'][0]['evidence_scope'], 'family_common')


if __name__ == '__main__':
    unittest.main()

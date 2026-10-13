"""외부 과금 없이 도구 실행·근거 검증·종료 조건을 확인한다."""
import json
import unittest
from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from backend.recommendation_service import RecommendationError, run_recommendation, validate_selection
from backend.recommendation_tools import RecommendationDataUnavailable


CERTIFICATE_ID = '79a6a7a3-5fbc-4b64-80dd-732206f3fb81'
CANDIDATE = {
    'certificate_id': CERTIFICATE_ID, 'name': '정보처리기사',
    'summary': '검토된 요약', 'related_jobs': [],
    'evidence_documents': [{'document_id': 'official:1320', 'content': '소프트웨어 개발 및 시스템 운영 업무를 수행한다.'}],
}


def create_final(certificate_id=CERTIFICATE_ID, quote='소프트웨어 개발'):
    return AIMessage(content=json.dumps({'status': 'completed', 'items': [{
        'certificate_id': certificate_id, 'reason': '컴퓨터공학 전공과 개발 업무가 연결됩니다.',
        'profile_factors': ['major'], 'evidence': [{'document_id': 'official:1320', 'quote': quote}],
    }]}, ensure_ascii=False))


def create_search(codes=None):
    return AIMessage(content='', tool_calls=[{
        'name': 'search_certificates', 'id': 'search-1',
        'args': {'interest_codes': codes or ['20'], 'search_terms': ['소프트웨어']},
    }])


class RecommendationServiceTests(unittest.TestCase):
    def setUp(self):
        self.search = Mock(name='search')
        self.search.name = 'search_certificates'
        self.search.invoke.return_value = {'status': 'found', 'candidates': [CANDIDATE]}
        self.model = Mock()
        self.bound = self.model.bind_tools.return_value

    def run_service(self):
        return run_recommendation({'major': '컴퓨터공학'}, ['20'], model=self.model, tools=[self.search])

    def test_executes_tool_and_returns_db_context_with_matching_message_id(self):
        self.bound.invoke.side_effect = [create_search(), create_final()]
        result = self.run_service()
        self.assertEqual(result['selection']['items'][0]['certificate_id'], CERTIFICATE_ID)
        self.assertEqual(result['candidates'][0]['related_jobs'], [])
        messages = self.bound.invoke.call_args.args[0]
        tool_message = next(message for message in messages if isinstance(message, ToolMessage))
        self.assertEqual(tool_message.tool_call_id, 'search-1')
        self.assertEqual(result['tool_call_count'], 1)

    def test_unknown_id_is_repaired_once_then_rejected(self):
        self.bound.invoke.side_effect = [create_search(), create_final('invented'), create_final('invented')]
        with self.assertRaises(RecommendationError) as caught:
            self.run_service()
        self.assertEqual(caught.exception.code, 'invalid_result')
        self.assertEqual(self.bound.invoke.call_count, 3)

    def test_changed_quote_can_be_repaired_without_another_search(self):
        self.bound.invoke.side_effect = [create_search(), create_final(quote='소프트웨어를 개발한다'), create_final()]
        result = self.run_service()
        self.assertEqual(result['repair_count'], 1)
        self.assertEqual(self.search.invoke.call_count, 1)

    def test_db_failure_does_not_become_no_results(self):
        self.bound.invoke.side_effect = [create_search()]
        self.search.invoke.side_effect = RecommendationDataUnavailable('DB 실패')
        with self.assertRaises(RecommendationError) as caught:
            self.run_service()
        self.assertEqual(caught.exception.code, 'data_unavailable')

    def test_cannot_change_user_interest_codes(self):
        self.bound.invoke.side_effect = [create_search(['03']), create_search(['03'])]
        with self.assertRaises(RecommendationError):
            self.run_service()
        self.search.invoke.assert_not_called()

    def test_cannot_finish_before_search(self):
        self.bound.invoke.side_effect = [AIMessage(content='{"status":"no_results","items":[]}')] * 2
        with self.assertRaises(RecommendationError):
            self.run_service()

    def test_empty_search_is_valid_but_scope_is_limited(self):
        self.search.invoke.return_value = {'status': 'empty_search', 'candidates': []}
        self.bound.invoke.side_effect = [create_search(), AIMessage(content='{"status":"no_results","items":[]}')]
        result = self.run_service()
        self.assertEqual(result['selection']['status'], 'no_results')
        self.assertEqual(result['selection_scope'], 'searched_candidates_only')

    def test_repeated_searches_stop_at_limit(self):
        self.bound.invoke.side_effect = [AIMessage(content='', tool_calls=[{
            'name': 'search_certificates', 'id': f'search-{number}',
            'args': {'interest_codes': ['20'], 'search_terms': ['개발']},
        }]) for number in range(10)]
        with self.assertRaises(RecommendationError) as caught:
            self.run_service()
        self.assertEqual(caught.exception.code, 'execution_limit')
        self.assertLessEqual(self.search.invoke.call_count, 6)

    def test_rejects_duplicate_more_than_ten_and_wrong_source(self):
        original = json.loads(create_final().content)
        duplicate = dict(original, items=original['items'] * 2)
        too_many = dict(original, items=original['items'] * 11)
        wrong_source = json.loads(create_final().content)
        wrong_source['items'][0]['evidence'][0]['document_id'] = 'another-certificate'
        for output in [duplicate, too_many, wrong_source]:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    validate_selection(json.dumps(output), {CERTIFICATE_ID: CANDIDATE}, {'major': '컴퓨터공학'}, True)

    def test_rejects_invented_profile_factor_and_inconsistent_status(self):
        invented = json.loads(create_final().content)
        invented['items'][0]['profile_factors'] = ['career_years']
        inconsistent = dict(invented, status='no_results')
        for output in [invented, inconsistent]:
            with self.assertRaises(ValueError):
                validate_selection(json.dumps(output), {CERTIFICATE_ID: CANDIDATE}, {'major': '컴퓨터공학'}, True)

    def test_unknown_tool_is_never_executed(self):
        response = AIMessage(content='', tool_calls=[{
            'name': 'create_calendar_event', 'id': 'forbidden', 'args': {},
        }])
        second = AIMessage(content='', tool_calls=[{
            'name': 'create_calendar_event', 'id': 'forbidden-again', 'args': {},
        }])
        self.bound.invoke.side_effect = [response, second]
        with self.assertRaises(RecommendationError) as caught:
            self.run_service()
        self.assertEqual(caught.exception.code, 'invalid_tool_call')
        self.search.invoke.assert_not_called()


if __name__ == '__main__':
    unittest.main()

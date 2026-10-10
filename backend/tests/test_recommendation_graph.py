"""실제 StateGraph의 정상·수정·재시도·오류 종료 경로를 확인한다."""
import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, ToolMessage
import httpx
from openai import APITimeoutError, AuthenticationError

from backend.recommendation_graph import create_recommendation_graph, MAX_CONTEXT_CHARACTERS
from backend.recommendation_tools import RecommendationDataUnavailable
from backend.tests.test_recommendation_service import CANDIDATE, create_final, create_search


class RecommendationGraphTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock()
        self.bound = self.model.bind_tools.return_value
        self.search = Mock()
        self.search.name = 'search_certificates'
        self.search.invoke.return_value = {'status': 'found', 'candidates': [CANDIDATE]}

    def run_graph(self):
        graph = create_recommendation_graph(self.model, [self.search])
        return graph.invoke({'profile': {'major': '컴퓨터공학'}, 'interest_codes': ['20']},
                            {'recursion_limit': 60})

    def test_normal_path_has_explicit_nodes_and_typed_state_counts(self):
        self.bound.invoke.side_effect = [create_search(), create_final()]
        state = self.run_graph()
        self.assertEqual(state['node_history'], ['prepare', 'context', 'decision', 'tools',
                                               'context', 'decision', 'validate', 'finish'])
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['tools_called'], ['search_certificates'])
        self.assertEqual(state['error_count'], 0)

    def test_transient_db_error_retries_same_call_once_then_succeeds(self):
        self.search.invoke.side_effect = [RecommendationDataUnavailable('一時失敗'),
                                         {'status': 'found', 'candidates': [CANDIDATE]}]
        self.bound.invoke.side_effect = [create_search(), create_final()]
        state = self.run_graph()
        self.assertEqual(state['retry_count'], 1)
        self.assertEqual(state['tool_call_count'], 2)
        self.assertIn('retry', state['node_history'])
        messages = self.bound.invoke.call_args.args[0]
        self.assertEqual(sum(isinstance(message, ToolMessage) for message in messages), 1)
        self.assertEqual(state['errors'][0]['repair_action'], 'retry_tool')

    def test_permanent_db_error_ends_at_fallback_not_empty_success(self):
        self.search.invoke.side_effect = RecommendationDataUnavailable('private connection value')
        self.bound.invoke.side_effect = [create_search()]
        state = self.run_graph()
        self.assertEqual(state['status'], 'failed')
        self.assertIsNone(state['result'])
        self.assertEqual(state['error']['code'], 'data_unavailable')
        self.assertEqual(self.search.invoke.call_count, 2)
        self.assertEqual(state['node_history'][-1], 'fallback')
        self.assertNotIn('private connection', json.dumps(state['errors']))

    def test_bad_quote_is_repaired_and_revalidated(self):
        self.bound.invoke.side_effect = [create_search(), create_final(quote='invented'), create_final()]
        state = self.run_graph()
        self.assertEqual(state['repair_count'], 1)
        self.assertEqual(state['node_history'].count('validate'), 2)
        self.assertEqual(state['errors'][0]['repair_action'], 'repair_result')
        self.assertEqual(state['errors'][0]['error_type'], 'quote_mismatch')
        self.assertEqual(state['status'], 'completed')

    def test_invalid_argument_batch_is_closed_with_matching_tool_messages(self):
        batch = AIMessage(content='', tool_calls=[
            {'name': 'search_certificates', 'id': 'bad', 'args': {'interest_codes': ['03']}},
            {'name': 'search_certificates', 'id': 'good',
             'args': {'interest_codes': ['20'], 'search_terms': ['개발']}},
        ])
        self.bound.invoke.side_effect = [batch, create_final()]
        state = self.run_graph()
        messages = self.bound.invoke.call_args.args[0]
        self.assertEqual([message.tool_call_id for message in messages if isinstance(message, ToolMessage)],
                         ['bad', 'good'])
        self.assertEqual(state['repair_count'], 1)
        self.assertEqual(self.search.invoke.call_count, 1)

    def test_no_result_does_not_retry_or_ask_user(self):
        self.search.invoke.return_value = {'status': 'empty_search', 'candidates': []}
        self.bound.invoke.side_effect = [create_search(), AIMessage(content='{"status":"no_results","items":[]}')]
        state = self.run_graph()
        self.assertEqual(state['status'], 'no_results')
        self.assertEqual(state['retry_count'], 0)
        self.assertNotIn('repair', state['node_history'])

    def test_context_size_limit_fails_before_model_call(self):
        graph = create_recommendation_graph(self.model, [self.search])
        state = graph.invoke({'profile': {'major': 'x' * (MAX_CONTEXT_CHARACTERS + 1)},
                              'interest_codes': ['20']})
        self.assertEqual(state['error']['code'], 'context_limit')
        self.bound.invoke.assert_not_called()

    def test_context_compaction_preserves_exact_evidence_and_db_payload(self):
        candidate = dict(CANDIDATE, raw_irrelevant_metadata='x' * MAX_CONTEXT_CHARACTERS)
        self.search.invoke.return_value = {'status': 'found', 'candidates': [candidate]}
        self.bound.invoke.side_effect = [create_search(), create_final()]
        state = self.run_graph()
        self.assertEqual(state['status'], 'completed')
        messages = self.bound.invoke.call_args.args[0]
        tool_message = next(message for message in messages if isinstance(message, ToolMessage))
        self.assertNotIn('raw_irrelevant_metadata', tool_message.content)
        self.assertIn('소프트웨어 개발', tool_message.content)
        self.assertEqual(state['result']['candidates'][0]['raw_irrelevant_metadata'], candidate['raw_irrelevant_metadata'])

    def test_new_run_does_not_reuse_previous_user_candidates(self):
        self.bound.invoke.side_effect = [create_search(), create_final(), create_final(), create_final()]
        graph = create_recommendation_graph(self.model, [self.search])
        first = graph.invoke({'profile': {'major': '컴퓨터공학'}, 'interest_codes': ['20']})
        second = graph.invoke({'profile': {'major': '회계'}, 'interest_codes': ['02']})
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(second['status'], 'failed')
        self.assertEqual(second['candidates'], {})

    def test_non_retryable_db_configuration_error_stops_immediately(self):
        self.search.invoke.side_effect = RecommendationDataUnavailable('설정 누락', retryable=False)
        self.bound.invoke.side_effect = [create_search()]
        state = self.run_graph()
        self.assertEqual(state['retry_count'], 0)
        self.assertEqual(self.search.invoke.call_count, 1)
        self.assertEqual(state['status'], 'failed')

    def test_model_timeout_retries_once_before_success(self):
        timeout = APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com/v1/chat/completions'))
        self.bound.invoke.side_effect = [timeout, create_search(), create_final()]
        state = self.run_graph()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['retry_count'], 1)
        self.assertEqual(state['model_call_count'], 3)
        self.assertEqual(state['errors'][0]['repair_action'], 'retry_model')

    def test_authentication_error_is_not_retried_or_exposed(self):
        response = httpx.Response(401, request=httpx.Request('POST', 'https://api.openai.com'))
        self.bound.invoke.side_effect = AuthenticationError('secret-like text', response=response, body=None)
        state = self.run_graph()
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['retry_count'], 0)
        self.assertEqual(self.bound.invoke.call_count, 1)
        self.assertNotIn('secret-like', json.dumps(state['errors']))

    def test_elapsed_budget_stops_before_model_call(self):
        with patch('backend.recommendation_graph.time.monotonic', side_effect=[0, 121]):
            state = self.run_graph()
        self.assertEqual(state['error']['code'], 'timeout')
        self.bound.invoke.assert_not_called()

    def test_malformed_function_arguments_get_tool_feedback_before_retry(self):
        malformed = AIMessage(content='', invalid_tool_calls=[{
            'name': 'search_certificates', 'args': '{broken json', 'id': 'broken', 'error': 'parse failure',
        }])
        self.bound.invoke.side_effect = [malformed, create_search(), create_final()]
        state = self.run_graph()
        self.assertEqual(state['status'], 'completed')
        second_messages = self.bound.invoke.call_args_list[1].args[0]
        self.assertTrue(any(isinstance(message, ToolMessage) and message.tool_call_id == 'broken'
                            for message in second_messages))
        self.assertEqual(state['errors'][0]['repair_action'], 'repair_tool_arguments')


if __name__ == '__main__':
    unittest.main()

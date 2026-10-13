"""후보 검색의 입력 제한·안전한 SQL·직업 미확인·도구 실패를 검사한다."""
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from pydantic import ValidationError

from backend.db.recommendation_repository import search_recommendation_candidates
from backend.recommendation_tools import (
    list_interest_categories, search_certificates, RecommendationDataUnavailable,
)


def create_connection():
    connection = MagicMock()
    choices = [{'code': '20', 'payload': {'code': '20', 'name': '정보통신'}}]
    payload = {'certificate_id': 'example-id', 'qnet_code': '1320', 'name': '정보처리기사',
               'summary': '공식 요약', 'related_jobs': [], 'evidence_documents': []}
    connection.execute.return_value.fetchall.return_value = choices
    return connection, choices, {'payload': payload}


class RecommendationToolTests(unittest.TestCase):
    def test_search_uses_literal_bound_terms_and_paginates(self):
        connection, choices, record = create_connection()
        connection.execute.side_effect = [MagicMock(fetchall=MagicMock(return_value=choices)),
                                         MagicMock(fetchall=MagicMock(return_value=[record, record]))]
        term = "개발%' OR 1=1 --"
        result = search_recommendation_candidates(connection, ['20'], [term], limit=1)
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(result['has_more'])
        self.assertEqual(result['next_offset'], 1)
        query, parameters = connection.execute.call_args.args
        self.assertNotIn(term, query)
        self.assertIn(term, parameters)
        self.assertIn('strpos', query)
        self.assertEqual(result['candidates'][0]['related_jobs'], [])
        self.assertEqual(result['selection_scope'], 'searched_candidates_only')

    def test_invalid_input_does_not_query_database(self):
        for codes, terms, limit, offset in [([], ['개발'], 20, 0), (['20','20'], ['개발'], 20, 0),
                                            (['20'], [' '], 20, 0), (['20'], ['개발'], 31, 0),
                                            (['20'], ['개발'], 20, -1)]:
            connection, _, _ = create_connection()
            with self.assertRaises(ValueError):
                search_recommendation_candidates(connection, codes, terms, limit, offset)
            connection.execute.assert_not_called()

    def test_unknown_interest_is_not_a_fixed_mapping(self):
        connection, _, _ = create_connection()
        with self.assertRaises(ValueError):
            search_recommendation_candidates(connection, ['99'], ['개발'])
        self.assertEqual(connection.execute.call_count, 1)

    def test_empty_search_is_not_global_no_results(self):
        connection, choices, _ = create_connection()
        connection.execute.side_effect = [MagicMock(fetchall=MagicMock(return_value=choices)),
                                         MagicMock(fetchall=MagicMock(return_value=[]))]
        result = search_recommendation_candidates(connection, ['20'], ['없는 검색어'])
        self.assertEqual(result['status'], 'empty_search')
        self.assertEqual(result['candidates'], [])
        self.assertFalse(result['has_more'])

    def test_tool_invoke_uses_read_only_connection(self):
        connection, choices, record = create_connection()
        connection.execute.side_effect = [MagicMock(), MagicMock(), MagicMock(fetchall=MagicMock(return_value=choices)),
                                         MagicMock(fetchall=MagicMock(return_value=[record]))]
        with patch('backend.recommendation_tools.database_connection') as manager:
            manager.return_value.__enter__.return_value = connection
            result = search_certificates.invoke({'interest_codes':['20'], 'search_terms':['개발']})
        self.assertEqual(result['status'], 'found')
        self.assertEqual(connection.execute.call_args_list[0].args[0], 'SET TRANSACTION READ ONLY')
        manager.return_value.__exit__.assert_called_once()

    def test_tool_input_schema_rejects_large_requests(self):
        with patch('backend.recommendation_tools.database_connection') as manager:
            with self.assertRaises(ValidationError):
                search_certificates.invoke({'interest_codes':['20'], 'search_terms':['개발'], 'limit':100})
            manager.assert_not_called()

    def test_database_failure_is_not_empty_success_and_hides_details(self):
        with patch('backend.recommendation_tools.database_connection') as manager:
            manager.side_effect = psycopg.OperationalError('private-connection-detail')
            with self.assertRaises(RecommendationDataUnavailable) as caught:
                search_certificates.invoke({'interest_codes':['20'], 'search_terms':['개발']})
            self.assertNotIn('private-connection-detail', str(caught.exception))

    def test_interest_tool_keeps_service_choice_metadata(self):
        connection, _, _ = create_connection()
        with patch('backend.recommendation_tools.database_connection') as manager:
            manager.return_value.__enter__.return_value = connection
            result = list_interest_categories.invoke({})
        self.assertEqual(result['classification_type'], 'project_interest')
        self.assertFalse(result['is_official_ncs_mapping'])
        self.assertEqual(result['items'][0]['code'], '20')


if __name__ == '__main__':
    unittest.main()

"""DB 미설정·장애 상황에도 공통 앱이 실행되는지 확인한다."""

import os
import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from backend.main import app


class BootstrapTests(unittest.TestCase):
    """상태 API와 API 문서의 공통 계약을 검사한다."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_app_runs_without_database_settings(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.get('/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'status': 'ok', 'database_configured': False})
            database = self.client.get('/health/database')
            self.assertEqual(database.status_code, 503)
            self.assertEqual(database.json()['status'], 'not_configured')

    def test_database_error_does_not_expose_credentials(self) -> None:
        with patch.dict(os.environ, {'DATABASE_URL': 'private-test-value'}):
            with patch('backend.db.check.database_connection', side_effect=psycopg.OperationalError('private-test-value')):
                response = self.client.get('/health/database')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'unavailable')
        self.assertNotIn('private-test-value', response.text)

    def test_ready_database_and_documented_routes(self) -> None:
        ready = {'configured': True, 'connected': True, 'tables_ready': True,
                 'missing_tables': [], 'status': 'ready'}
        with patch('backend.main.check_database', return_value=ready):
            response = self.client.get('/health/database')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ready)
        self.assertEqual(self.client.get('/docs').status_code, 200)
        self.assertEqual(set(self.client.get('/openapi.json').json()['paths']), {'/health', '/health/database'})


if __name__ == '__main__':
    unittest.main()

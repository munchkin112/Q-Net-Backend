"""로그인 없이 제공하는 관심 분야 목록 계약을 검증한다."""
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.profile_router import create_profile_router


class PublicInterestCategoryTests(unittest.TestCase):
    def client(self, read_interests=None):
        app = FastAPI()
        self.read_interests = read_interests or Mock(return_value=[
            {"code": "20", "name": "정보통신"},
        ])
        app.include_router(create_profile_router(read_interests=self.read_interests))
        return TestClient(app)

    def test_interest_categories_are_public(self):
        response = self.client().get("/interest-categories")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"code": "20", "name": "정보통신"}])
        self.read_interests.assert_called_once_with()

    def test_profile_storage_endpoints_are_removed(self):
        client = self.client()

        self.assertEqual(client.get("/me/profile").status_code, 404)
        self.assertEqual(client.patch("/me/profile", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()


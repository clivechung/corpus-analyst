"""Unit tests for FastAPI Query Engine REST API seam (SEAM-QUERY-API).

Follows TREM principles:
- Testable: In-memory ASGI test client via httpx and FastAPI dependency injection overrides.
- Readable: Direct assertions on HTTP status codes and Pydantic schemas.
- Maintainable: Verification of public API boundaries and error envelopes.
"""

import unittest
from fastapi.testclient import TestClient

from src.common.config import Settings
from src.query_engine.main import app, get_app_settings


class TestQueryEngineApiSeam(unittest.TestCase):
    """Test suite for the Query Engine API endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_healthz_liveness_probe(self) -> None:
        """Verify GET /healthz returns 200 OK and expected service status."""
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "query-engine")

    def test_api_v1_health_probe(self) -> None:
        """Verify GET /api/v1/health returns detailed health information."""
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)
        self.assertIn("environment", data)
        self.assertIn("default_domain", data)

    def test_settings_dependency_injection_override(self) -> None:
        """Verify settings can be injected via FastAPI dependency overrides (TREM: Testable)."""
        mock_settings = Settings()
        mock_settings.app.env = "staging-test"
        mock_settings.app.default_domain = "literature"

        app.dependency_overrides[get_app_settings] = lambda: mock_settings
        try:
            response = self.client.get("/api/v1/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["environment"], "staging-test")
            self.assertEqual(data["default_domain"], "literature")
        finally:
            app.dependency_overrides.clear()

    def test_query_endpoint_validation_and_response_contract(self) -> None:
        """Verify POST /api/v1/query accepts valid QueryRequest and validates inputs."""
        payload = {
            "question": "What were the total revenues for fiscal 2024?",
            "domain": "finance",
            "top_k": 5,
            "similarity_threshold": 0.5,
        }
        response = self.client.post("/api/v1/query", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["question"], payload["question"])
        self.assertEqual(data["domain"], "finance")
        self.assertIn("answer", data)
        self.assertIn("retrieved_chunks", data)
        self.assertIn("citations", data)

    def test_query_endpoint_invalid_payload_returns_422(self) -> None:
        """Verify POST /api/v1/query with invalid top_k returns 422 Unprocessable Entity."""
        invalid_payload = {
            "question": "Test question",
            "top_k": -1,  # Invalid: must be >= 1
        }
        response = self.client.post("/api/v1/query", json=invalid_payload)
        self.assertEqual(response.status_code, 422)

    def test_search_endpoint_returns_candidates_contract(self) -> None:
        """Verify POST /api/v1/search accepts search request and returns candidate context list."""
        payload = {
            "question": "Data Center GPU demand",
            "domain": "finance",
            "top_k": 3,
        }
        response = self.client.post("/api/v1/search", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)


if __name__ == "__main__":
    unittest.main()


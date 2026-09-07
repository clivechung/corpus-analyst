"""Unit tests for FastAPI Query Engine REST API seam (SEAM-QUERY-API).

Follows TREM principles:
- Testable: In-memory ASGI test client via httpx and FastAPI dependency injection overrides.
- Readable: Direct assertions on HTTP status codes and Pydantic schemas.
- Maintainable: Verification of public API boundaries, error envelopes, and citation grounding.
"""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.common.config import Settings
from src.common.models import RetrievedContextChunk
from src.ingestion.embedder import EmbeddingRegistry
from src.query_engine.duckdb_client import DuckDBLakehouseClient
from src.query_engine.main import (
    app,
    get_app_settings,
    get_query_duckdb_client,
    get_query_embedding_registry,
)


class TestQueryEngineApiSeam(unittest.TestCase):
    """Test suite for the Query Engine API endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_healthz_liveness_probe(self) -> None:
        """Verify GET /healthz returns 200 OK and expected service status."""
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "query-engine")

    def test_api_v1_health_probe(self) -> None:
        """Verify GET /api/v1/health returns detailed health information with lake stats."""
        mock_duckdb = MagicMock(spec=DuckDBLakehouseClient)
        mock_duckdb.get_lake_stats.return_value = {
            "total_parquet_files": 12,
            "total_size_bytes": 1048576,
            "domains": ["finance", "literature"],
        }
        app.dependency_overrides[get_query_duckdb_client] = lambda: mock_duckdb

        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)
        self.assertIn("environment", data)
        self.assertIn("default_domain", data)
        self.assertEqual(data["total_parquet_files"], 12)
        self.assertEqual(data["domains"], ["finance", "literature"])

    def test_settings_dependency_injection_override(self) -> None:
        """Verify settings can be injected via FastAPI dependency overrides (TREM: Testable)."""
        mock_settings = Settings()
        mock_settings.app.env = "staging-test"
        mock_settings.app.default_domain = "literature"

        app.dependency_overrides[get_app_settings] = lambda: mock_settings
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["environment"], "staging-test")
        self.assertEqual(data["default_domain"], "literature")

    def test_search_endpoint_with_retrieved_chunks(self) -> None:
        """Verify POST /api/v1/search uses embedder and returns candidate chunks."""
        mock_registry = EmbeddingRegistry(use_mock=True)
        mock_duckdb = MagicMock(spec=DuckDBLakehouseClient)
        mock_duckdb.search.return_value = [
            RetrievedContextChunk(
                chunk_id="chunk-101",
                source_filename="NVDA_10-K_20240221.htm",
                section="Item 7 - MD&A",
                text="Gross margins expanded to 75.0%.",
                is_table=False,
                similarity_score=0.925,
                form_type="10-K",
                filing_date=date(2024, 2, 21),
            )
        ]

        app.dependency_overrides[get_query_embedding_registry] = lambda: mock_registry
        app.dependency_overrides[get_query_duckdb_client] = lambda: mock_duckdb

        payload = {
            "question": "NVIDIA margins",
            "domain": "finance",
            "top_k": 3,
        }
        response = self.client.post("/api/v1/search", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["chunk_id"], "chunk-101")
        self.assertEqual(data[0]["source_filename"], "NVDA_10-K_20240221.htm")
        self.assertAlmostEqual(data[0]["similarity_score"], 0.925)

    def test_query_endpoint_with_grounded_citations(self) -> None:
        """Verify POST /api/v1/query returns grounded synthesis and traceable citations."""
        mock_registry = EmbeddingRegistry(use_mock=True)
        mock_duckdb = MagicMock(spec=DuckDBLakehouseClient)
        mock_duckdb.search.return_value = [
            RetrievedContextChunk(
                chunk_id="c-alpha",
                source_filename="AMZN_10-K_2024.htm",
                section="Item 7",
                text="AWS segment sales increased 13% year-over-year.",
                is_table=False,
                similarity_score=0.884,
                form_type="10-K",
                filing_date=date(2024, 2, 6),
            )
        ]

        app.dependency_overrides[get_query_embedding_registry] = lambda: mock_registry
        app.dependency_overrides[get_query_duckdb_client] = lambda: mock_duckdb

        payload = {
            "question": "What was AWS growth?",
            "domain": "finance",
            "top_k": 5,
        }
        response = self.client.post("/api/v1/query", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["question"], payload["question"])
        self.assertEqual(data["domain"], "finance")
        self.assertIn("AWS segment sales", data["answer"])
        self.assertEqual(len(data["retrieved_chunks"]), 1)
        self.assertEqual(len(data["citations"]), 1)

        citation = data["citations"][0]
        self.assertEqual(citation["source_filename"], "AMZN_10-K_2024.htm")
        self.assertEqual(citation["section"], "Item 7")
        self.assertEqual(citation["chunk_id"], "c-alpha")
        self.assertAlmostEqual(citation["similarity_score"], 0.884)
        self.assertIn("AWS segment sales", citation["excerpt"])
        self.assertGreater(data["latency_ms"], 0.0)

    def test_query_endpoint_empty_results_handling(self) -> None:
        """Verify POST /api/v1/query gracefully handles queries with no matching chunks."""
        mock_registry = EmbeddingRegistry(use_mock=True)
        mock_duckdb = MagicMock(spec=DuckDBLakehouseClient)
        mock_duckdb.search.return_value = []

        app.dependency_overrides[get_query_embedding_registry] = lambda: mock_registry
        app.dependency_overrides[get_query_duckdb_client] = lambda: mock_duckdb

        payload = {
            "question": "Unknown obscure term",
            "domain": "finance",
            "top_k": 5,
        }
        response = self.client.post("/api/v1/query", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["retrieved_chunks"], [])
        self.assertEqual(data["citations"], [])
        self.assertIn("No relevant context chunks", data["answer"])

    def test_query_endpoint_invalid_payload_returns_422(self) -> None:
        """Verify POST /api/v1/query with invalid top_k returns 422 Unprocessable Entity."""
        invalid_payload = {
            "question": "Test question",
            "top_k": -1,  # Invalid: must be >= 1
        }
        response = self.client.post("/api/v1/query", json=invalid_payload)
        self.assertEqual(response.status_code, 422)

    def test_sql_endpoint_success(self) -> None:
        """Verify POST /api/v1/sql executes query and returns columns, rows, and latency."""
        mock_duckdb = MagicMock(spec=DuckDBLakehouseClient)
        mock_duckdb.execute_sql.return_value = (["col1", "col2"], [(1, "val1"), (2, "val2")])
        app.dependency_overrides[get_query_duckdb_client] = lambda: mock_duckdb

        payload = {"query": "SELECT col1, col2 FROM test"}
        response = self.client.post("/api/v1/sql", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["columns"], ["col1", "col2"])
        self.assertEqual(data["rows"], [[1, "val1"], [2, "val2"]])
        self.assertGreaterEqual(data["duration_ms"], 0.0)

    def test_sql_endpoint_forbidden_mutation_returns_403(self) -> None:
        """Verify POST /api/v1/sql returns 403 Forbidden when mutative query is attempted."""
        mock_duckdb = MagicMock(spec=DuckDBLakehouseClient)
        mock_duckdb.execute_sql.side_effect = PermissionError("Mutative operation rejected.")
        app.dependency_overrides[get_query_duckdb_client] = lambda: mock_duckdb

        payload = {"query": "DROP TABLE chunks"}
        response = self.client.post("/api/v1/sql", json=payload)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Security guard", response.json()["detail"])

    def test_embed_endpoint_success(self) -> None:
        """Verify POST /api/v1/embed returns computed vector and dimension."""
        from src.ingestion.embedder import EmbeddingRegistry, get_embedding_registry as get_query_embedding_registry

        mock_registry = EmbeddingRegistry(use_mock=True)
        app.dependency_overrides[get_query_embedding_registry] = lambda: mock_registry

        payload = {"text": "Google 2026 revenue", "domain": "finance"}
        response = self.client.post("/api/v1/embed", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["text"], "Google 2026 revenue")
        self.assertEqual(data["dimension"], 384)
        self.assertEqual(len(data["embedding"]), 384)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for shared Pydantic data schemas seam (TREM: Testable, Readable, Maintainable)."""

import json
from datetime import date
from uuid import UUID, uuid4
import unittest
from pydantic import ValidationError

from src.common.models import (
    Chunk,
    Citation,
    DocumentMetadata,
    DomainType,
    FormType,
    QueryRequest,
    QueryResponse,
    RetrievedContextChunk,
)


class TestModelsSeam(unittest.TestCase):
    """Test suite for the public models and data contracts seam."""

    def test_document_metadata_valid(self) -> None:
        """Verify DocumentMetadata creation and default values."""
        meta = DocumentMetadata(
            doc_id="sec-nvda-10k-2024",
            source_filename="nvda-202410k.htm",
            domain=DomainType.FINANCE,
            form_type=FormType.SEC_10K,
            filing_date=date(2024, 2, 21),
            company_name="NVIDIA CORP",
            ticker="NVDA",
        )
        self.assertEqual(meta.doc_id, "sec-nvda-10k-2024")
        self.assertEqual(meta.ticker, "NVDA")
        self.assertEqual(meta.form_type, FormType.SEC_10K)
        self.assertEqual(meta.domain, "finance")

    def test_chunk_creation_and_parquet_dict(self) -> None:
        """Verify Chunk UUID generation and to_parquet_dict serialization for lakehouse sink."""
        embedding_vec = [0.12, -0.45, 0.88, 0.01]
        chunk = Chunk(
            doc_id="sec-nvda-10k-2024",
            domain=DomainType.FINANCE,
            source_filename="nvda-202410k.htm",
            form_type=FormType.SEC_10K,
            filing_date=date(2024, 2, 21),
            section="Item 7. Management's Discussion and Analysis",
            is_table=True,
            text="Revenue for fiscal year 2024 was $60.9 billion, up 126% from a year ago.",
            embedding=embedding_vec,
            page_number=42,
            token_count=18,
            metadata={"table_headers": ["Year", "Revenue"]},
        )

        self.assertIsInstance(chunk.chunk_id, UUID)
        self.assertTrue(chunk.is_table)

        parquet_row = chunk.to_parquet_dict()
        self.assertEqual(parquet_row["chunk_id"], str(chunk.chunk_id))
        self.assertEqual(parquet_row["doc_id"], "sec-nvda-10k-2024")
        self.assertEqual(parquet_row["domain"], "finance")
        self.assertEqual(parquet_row["source_filename"], "nvda-202410k.htm")
        self.assertEqual(parquet_row["form_type"], "10-K")
        self.assertEqual(parquet_row["filing_date"], date(2024, 2, 21))
        self.assertEqual(parquet_row["section"], "Item 7. Management's Discussion and Analysis")
        self.assertTrue(parquet_row["is_table"])
        self.assertEqual(parquet_row["text"], chunk.text)
        self.assertEqual(parquet_row["embedding"], embedding_vec)

        # metadata_json must be valid JSON containing page_number and extra metadata
        parsed_meta = json.loads(parquet_row["metadata_json"])
        self.assertEqual(parsed_meta["page_number"], 42)
        self.assertEqual(parsed_meta["table_headers"], ["Year", "Revenue"])

    def test_query_request_validation(self) -> None:
        """Verify validation constraints on QueryRequest."""
        # Valid query
        valid_req = QueryRequest(
            question="What was NVIDIA's data center revenue?",
            domain=DomainType.FINANCE,
            top_k=10,
            similarity_threshold=0.5,
        )
        self.assertEqual(valid_req.top_k, 10)
        self.assertEqual(valid_req.similarity_threshold, 0.5)

        # Invalid top_k: < 1
        with self.assertRaises(ValidationError):
            QueryRequest(question="Test question", top_k=0)

        # Invalid top_k: > 100
        with self.assertRaises(ValidationError):
            QueryRequest(question="Test question", top_k=101)

        # Invalid similarity threshold: < -1.0 or > 1.0
        with self.assertRaises(ValidationError):
            QueryRequest(question="Test question", similarity_threshold=1.5)

    def test_query_response_serialization(self) -> None:
        """Verify QueryResponse and Citation structure serialization."""
        retrieved_chunk = RetrievedContextChunk(
            chunk_id=str(uuid4()),
            source_filename="nvda-10k.htm",
            section="Item 7",
            text="Data Center revenue was $47.5 billion.",
            is_table=False,
            similarity_score=0.92,
            form_type="10-K",
            filing_date=date(2024, 2, 21),
        )
        citation = Citation(
            source_filename="nvda-10k.htm",
            section="Item 7",
            chunk_id=retrieved_chunk.chunk_id,
            similarity_score=0.92,
            excerpt="Data Center revenue was $47.5 billion.",
        )
        response = QueryResponse(
            question="What was Data Center revenue?",
            answer="NVIDIA Data Center revenue was $47.5 billion in fiscal 2024.",
            domain="finance",
            retrieved_chunks=[retrieved_chunk],
            citations=[citation],
            latency_ms=142.5,
            model_used="gemini-2.5-flash",
        )

        resp_dict = response.model_dump()
        self.assertEqual(len(resp_dict["citations"]), 1)
        self.assertEqual(resp_dict["citations"][0]["chunk_id"], retrieved_chunk.chunk_id)
        self.assertEqual(len(resp_dict["retrieved_chunks"]), 1)
        self.assertEqual(resp_dict["model_used"], "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()


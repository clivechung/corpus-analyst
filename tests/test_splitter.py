"""Tests for Phase 4 ING-04: Secondary Recursive Token Splitter & Lineage Tracking.

Verifies SEAM-SPLITTER:
- Strict chunk token bounding (token_count <= max_chunk_tokens)
- Delimiter hierarchy progression (\n\n -> \n -> .  -> space -> char fallback)
- Sliding window overlap (64 tokens context window across boundaries)
- Parent-child lineage tracking (parent_chunk_id, sub_chunk_index, total_sub_chunks)
- Passthrough behavior for chunks <= max_chunk_tokens
- HTML table chunk splitting and layout preservation (is_table=True, table_id)
- Edge cases: unbroken tokens, empty/whitespace strings
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.common.config import ChunkingSettings
from src.common.models import Chunk, DomainType, FormType
from src.ingestion.parser import estimate_token_count
from src.ingestion.splitter import ChunkSplitterProtocol, RecursiveTokenSplitter


class TestSplitterSeam:
    """Test suite validating SEAM-SPLITTER public interface and splitting contracts."""

    @pytest.fixture
    def default_splitter(self) -> RecursiveTokenSplitter:
        """Provide a default RecursiveTokenSplitter instance with standard settings."""
        settings = ChunkingSettings(max_chunk_tokens=512, chunk_overlap_tokens=64, max_characters=2000)
        return RecursiveTokenSplitter(settings=settings)

    def test_satisfies_splitter_protocol(self, default_splitter: RecursiveTokenSplitter) -> None:
        """Verify RecursiveTokenSplitter conforms to ChunkSplitterProtocol."""
        assert isinstance(default_splitter, ChunkSplitterProtocol)

    def test_passthrough_for_small_chunks(self, default_splitter: RecursiveTokenSplitter) -> None:
        """Verify chunks with token count <= max_chunk_tokens are returned untouched."""
        text = "Item 1A. Risk Factors: The semiconductor supply chain faces geopolitical risks."
        chunk = Chunk(
            chunk_id=uuid4(),
            doc_id="doc-test-1",
            domain=DomainType.FINANCE,
            source_filename="test.htm",
            section="Item 1A - Risk Factors",
            text=text,
            token_count=estimate_token_count(text),
        )

        sub_chunks = default_splitter.split_chunk(chunk)
        assert len(sub_chunks) == 1
        assert sub_chunks[0].chunk_id == chunk.chunk_id
        assert sub_chunks[0].parent_chunk_id is None
        assert sub_chunks[0].text == text
        assert sub_chunks[0].metadata.get("is_split", False) is False

    def test_split_text_bounds_all_chunks(self) -> None:
        """Verify split_text produces segments strictly <= max_chunk_tokens."""
        settings = ChunkingSettings(max_chunk_tokens=50, chunk_overlap_tokens=10, max_characters=200)
        splitter = RecursiveTokenSplitter(settings=settings)

        # Generate long text with paragraphs and sentences
        paragraphs = [
            f"Paragraph {i}: Revenue increased significantly in quarter {i} due to strong AI enterprise demand. "
            f"Gross margins expanded by {i * 2} basis points across all cloud compute segments. "
            f"Operating expenses grew at a disciplined rate relative to revenue generation."
            for i in range(1, 15)
        ]
        long_text = "\n\n".join(paragraphs)

        chunks = splitter.split_text(long_text, max_tokens=50, overlap_tokens=10)
        assert len(chunks) > 1

        for idx, chunk_text in enumerate(chunks):
            t_count = estimate_token_count(chunk_text)
            assert t_count <= 50, f"Chunk {idx} token count {t_count} exceeded max 50"
            assert len(chunk_text.strip()) > 0

    def test_sliding_window_overlap_retention(self) -> None:
        """Verify adjacent split chunks share context up to chunk_overlap_tokens."""
        settings = ChunkingSettings(max_chunk_tokens=60, chunk_overlap_tokens=15, max_characters=250)
        splitter = RecursiveTokenSplitter(settings=settings)

        words = [f"word{i}" for i in range(200)]
        long_text = " ".join(words)

        chunks = splitter.split_text(long_text, max_tokens=60, overlap_tokens=15)
        assert len(chunks) >= 3

        # Consecutive chunks must share overlap tokens
        for i in range(len(chunks) - 1):
            curr_words = chunks[i].split()
            next_words = chunks[i + 1].split()

            # The start of next_words should contain the tail of curr_words
            overlap_found = False
            for window in range(5, 16):
                tail = curr_words[-window:]
                head = next_words[:window]
                if tail == head:
                    overlap_found = True
                    break
            assert overlap_found, f"Expected sliding window overlap between chunk {i} and {i + 1}"

    def test_delimiter_hierarchy_progression(self) -> None:
        """Verify splitter respects delimiter order (\n\n, \n, sentence, word, char)."""
        settings = ChunkingSettings(max_chunk_tokens=40, chunk_overlap_tokens=0, max_characters=250)
        splitter = RecursiveTokenSplitter(settings=settings)

        # Text with clear paragraph breaks (each ~24 tokens, total ~48 tokens > max 40)
        p1 = (
            "Paragraph one discusses cloud computing architectures and distributed system topologies "
            "across multiple data center clusters to ensure high availability and resilient failover."
        )
        p2 = (
            "Paragraph two evaluates vector database indices and retrieval augmented generation pipelines "
            "for real-time document search to maximize relevance and minimize query latency."
        )
        text = f"{p1}\n\n{p2}"

        chunks = splitter.split_text(text, max_tokens=40, overlap_tokens=0)
        assert len(chunks) == 2
        assert "Paragraph one" in chunks[0]
        assert "Paragraph two" in chunks[1]

    def test_unbroken_text_character_fallback(self) -> None:
        """Verify unbroken continuous string with no spaces or delimiters is safely bounded."""
        settings = ChunkingSettings(max_chunk_tokens=50, chunk_overlap_tokens=10, max_characters=200)
        splitter = RecursiveTokenSplitter(settings=settings)

        # Massive continuous string without whitespace or punctuation
        unbroken = "A" * 1500

        chunks = splitter.split_text(unbroken, max_tokens=50, overlap_tokens=10)
        assert len(chunks) > 1

        for chunk_str in chunks:
            assert estimate_token_count(chunk_str) <= 50

    def test_parent_lineage_metadata_propagation(self, default_splitter: RecursiveTokenSplitter) -> None:
        """Verify split chunks preserve parent lineage, sequence indices, and document attributes."""
        # Create an oversized chunk (>512 tokens)
        sentences = [
            f"Sentence {i}: Management discusses operations and future growth projections for year 2026."
            for i in range(120)
        ]
        oversized_text = " ".join(sentences)
        parent_id = uuid4()

        parent_chunk = Chunk(
            chunk_id=parent_id,
            doc_id="doc-nvda-10k",
            domain=DomainType.FINANCE,
            source_filename="NVDA_10-K_20260225.htm",
            form_type=FormType.SEC_10K,
            section="Item 7 - Management's Discussion and Analysis",
            page_number=42,
            text=oversized_text,
            token_count=estimate_token_count(oversized_text),
            metadata={"original_key": "val123"},
        )
        assert parent_chunk.token_count > 512

        sub_chunks = default_splitter.split_chunk(parent_chunk)
        assert len(sub_chunks) > 1
        total = len(sub_chunks)

        for idx, child in enumerate(sub_chunks):
            # All sub-chunks must be strictly bounded
            assert child.token_count <= 512
            assert child.token_count == estimate_token_count(child.text)

            # Unique chunk_id
            assert child.chunk_id != parent_id
            assert isinstance(child.chunk_id, UUID)

            # Foreign key back to parent
            assert child.parent_chunk_id == parent_id

            # Inherited document attributes
            assert child.doc_id == "doc-nvda-10k"
            assert child.domain == DomainType.FINANCE
            assert child.source_filename == "NVDA_10-K_20260225.htm"
            assert child.form_type == FormType.SEC_10K
            assert child.section == "Item 7 - Management's Discussion and Analysis"
            assert child.page_number == 42
            assert child.is_table is False

            # Lineage metadata
            assert child.metadata["parent_chunk_id"] == str(parent_id)
            assert child.metadata["sub_chunk_index"] == idx
            assert child.metadata["total_sub_chunks"] == total
            assert child.metadata["is_split"] is True
            assert child.metadata["original_key"] == "val123"

    def test_tabular_chunk_splitting_preserves_table_flags(self) -> None:
        """Verify oversized financial table chunk splits into sub-chunks with is_table=True."""
        settings = ChunkingSettings(max_chunk_tokens=50, chunk_overlap_tokens=10, max_characters=200)
        splitter = RecursiveTokenSplitter(settings=settings)

        # Build a large HTML table
        rows = [
            f"<tr><td>Segment {i}</td><td>Revenue {i * 100}</td><td>Operating Margin {i * 1.5}%</td></tr>"
            for i in range(30)
        ]
        table_html = f"<table><thead><tr><th>Segment</th><th>Rev</th><th>Margin</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"

        parent_id = uuid4()
        parent_chunk = Chunk(
            chunk_id=parent_id,
            doc_id="doc-fin-1",
            domain=DomainType.FINANCE,
            source_filename="financials.htm",
            form_type=FormType.SEC_10K,
            section="Item 8 - Financial Statements",
            is_table=True,
            text=table_html,
            token_count=estimate_token_count(table_html),
            metadata={"table_html": table_html},
        )

        sub_chunks = splitter.split_chunk(parent_chunk)
        assert len(sub_chunks) > 1

        for child in sub_chunks:
            assert child.is_table is True
            assert child.token_count <= 50
            assert child.parent_chunk_id == parent_id
            assert child.metadata.get("table_id") == str(parent_id)
            assert child.metadata.get("is_table_fragment") is True

    def test_split_chunks_batch_operation(self, default_splitter: RecursiveTokenSplitter) -> None:
        """Verify split_chunks correctly processes mixed lists of normal and oversized chunks."""
        small_text = "Small normal section text."
        small_chunk = Chunk(
            chunk_id=uuid4(),
            doc_id="doc-1",
            domain=DomainType.FINANCE,
            source_filename="file.htm",
            text=small_text,
            token_count=estimate_token_count(small_text),
        )

        large_text = " ".join([f"Item {i} data point analysis." for i in range(150)])
        large_chunk = Chunk(
            chunk_id=uuid4(),
            doc_id="doc-1",
            domain=DomainType.FINANCE,
            source_filename="file.htm",
            text=large_text,
            token_count=estimate_token_count(large_text),
        )

        results = default_splitter.split_chunks([small_chunk, large_chunk])
        assert len(results) > 2
        # First chunk was small and passed through
        assert results[0].chunk_id == small_chunk.chunk_id
        assert results[0].parent_chunk_id is None

        # Subsequent chunks originated from large_chunk
        for ch in results[1:]:
            assert ch.parent_chunk_id == large_chunk.chunk_id
            assert ch.token_count <= 512

    def test_empty_and_whitespace_text_handling(self, default_splitter: RecursiveTokenSplitter) -> None:
        """Verify splitting empty or whitespace strings handles gracefully."""
        assert default_splitter.split_text("") == []
        assert default_splitter.split_text("   \n\n   ") == []

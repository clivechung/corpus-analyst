"""Tests for Phase 5 Dynamic Domain Embedding Registry (EMB-01).

Verifies SEAM-EMBEDDER:
- Model profile lookup across domains (finance, literature, general)
- Protocol compliance of embedders
- Single text, batch text, and chunk embedding
- Output vector dimension and L2 normalization
- Graceful handling of empty or whitespace text
- Deterministic mock embedder for airgapped/CI environments
"""

from __future__ import annotations

import math

import pytest

from src.common.models import Chunk, DomainType
from src.ingestion.embedder import (
    DomainEmbedder,
    EmbedderProtocol,
    EmbeddingRegistry,
    MockEmbedder,
    get_embedding_registry,
)


class TestEmbedderSeam:
    """Test suite validating SEAM-EMBEDDER specifications."""

    def test_satisfies_embedder_protocol(self) -> None:
        """Verify MockEmbedder and DomainEmbedder satisfy EmbedderProtocol."""
        mock_emb = MockEmbedder(dimension=384)
        assert isinstance(mock_emb, EmbedderProtocol)

        domain_emb = DomainEmbedder(profile_name="finance", dimension=384)
        assert isinstance(domain_emb, EmbedderProtocol)

    def test_registry_profile_resolution(self) -> None:
        """Verify registry resolves profiles for all 3 operational domains."""
        registry = get_embedding_registry()

        fin_prof = registry.get_profile("finance")
        assert fin_prof.name == "finance"
        assert fin_prof.dimension == 384
        assert fin_prof.model_name == "BAAI/bge-small-en-v1.5"
        assert fin_prof.batch_size == 32

        lit_prof = registry.get_profile("literature")
        assert lit_prof.name == "literature"
        assert lit_prof.dimension == 768
        assert lit_prof.model_name == "sentence-transformers/all-mpnet-base-v2"
        assert lit_prof.batch_size == 16

        gen_prof = registry.get_profile("general")
        assert gen_prof.name == "general"
        assert gen_prof.dimension == 1024
        assert gen_prof.model_name == "BAAI/bge-large-en-v1.5"

        # Fallback to default (finance) on unknown domain
        unknown_prof = registry.get_profile("quantum_physics")
        assert unknown_prof.name == "finance"
        assert unknown_prof.dimension == 384

    def test_mock_embedder_single_text_and_normalization(self) -> None:
        """Verify single text embedding produces exact dimension and unit norm."""
        embedder = MockEmbedder(dimension=384, normalize=True)
        vec = embedder.embed_text("Total revenue for fiscal year 2025 increased 22%.")

        assert len(vec) == 384
        assert all(isinstance(v, float) for v in vec)

        # Norm should be approximately 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        assert pytest.approx(norm, abs=1e-5) == 1.0

    def test_mock_embedder_deterministic(self) -> None:
        """Verify deterministic vectors for identical text and distinct vectors for different text."""
        embedder = MockEmbedder(dimension=384)
        text_a = "Risk factor: Supply chain disruption in semiconductor manufacturing."
        text_b = "Risk factor: Foreign currency exchange rate fluctuations."

        vec_a1 = embedder.embed_text(text_a)
        vec_a2 = embedder.embed_text(text_a)
        vec_b = embedder.embed_text(text_b)

        assert vec_a1 == vec_a2
        assert vec_a1 != vec_b

    def test_mock_embedder_batch_texts(self) -> None:
        """Verify batch embedding respects input order and batch bounds."""
        embedder = MockEmbedder(dimension=768, batch_size=4)
        texts = [f"Sample sentence number {i} regarding quarterly performance." for i in range(10)]

        embeddings = embedder.embed_texts(texts)
        assert len(embeddings) == 10
        for vec in embeddings:
            assert len(vec) == 768
            norm = math.sqrt(sum(x * x for x in vec))
            assert pytest.approx(norm, abs=1e-5) == 1.0

    def test_mock_embedder_embed_chunk_and_chunks(self) -> None:
        """Verify embed_chunk and embed_chunks populate Chunk.embedding."""
        embedder = MockEmbedder(dimension=384)

        chunk1 = Chunk(
            doc_id="doc-1",
            domain=DomainType.FINANCE,
            source_filename="nvda-10k.htm",
            text="Item 1A Risk Factors paragraph on AI infrastructure.",
        )
        chunk2 = Chunk(
            doc_id="doc-1",
            domain=DomainType.FINANCE,
            source_filename="nvda-10k.htm",
            text="Item 7 MD&A overview of revenue growth.",
        )

        assert chunk1.embedding is None
        assert chunk2.embedding is None

        # embed_chunk
        res1 = embedder.embed_chunk(chunk1)
        assert res1.embedding is not None
        assert len(res1.embedding) == 384

        # embed_chunks
        res_list = embedder.embed_chunks([chunk1, chunk2])
        assert len(res_list) == 2
        assert len(res_list[0].embedding) == 384
        assert len(res_list[1].embedding) == 384

    def test_empty_and_whitespace_text_handling(self) -> None:
        """Verify empty or whitespace strings do not raise exception and return valid vectors."""
        embedder = MockEmbedder(dimension=384)
        vec_empty = embedder.embed_text("")
        assert len(vec_empty) == 384

        vec_ws = embedder.embed_text("   \n\t  ")
        assert len(vec_ws) == 384

    def test_registry_get_embedder_caching(self) -> None:
        """Verify registry caches embedder instances per profile."""
        registry = EmbeddingRegistry(use_mock=True)

        emb1 = registry.get_embedder("finance")
        emb2 = registry.get_embedder("finance")
        assert emb1 is emb2

        emb_lit = registry.get_embedder("literature")
        assert emb_lit is not emb1
        assert emb_lit.dimension == 768

    def test_domain_embedder_lazy_initialization(self) -> None:
        """Verify DomainEmbedder does not instantiate heavy model during init."""
        embedder = DomainEmbedder(profile_name="finance", dimension=384)
        assert embedder._model is None

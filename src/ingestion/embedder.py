"""Dynamic Domain Embedding Registry and dense vector inference engine (EMB-01).

Follows TREM-Python principles:
- Testable: EmbedderProtocol contract with MockEmbedder for deterministic, offline,
  and sub-second test execution without network model downloads.
- Readable: Explicit type annotations, dataclasses/protocols, and structured logging.
- Extensible: Runtime-selectable domain embedding registry configured via models.json
  supporting finance, literature, and general corpus domains.
- Maintainable: Lazy loading of transformer weights to optimize memory consumption,
  local weight caching in persistent volume, and automatic L2 normalization.
"""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from src.common.config import (
    EmbeddingModelProfile,
    ModelRegistryConfig,
    Settings,
    get_settings,
    load_model_profiles,
)
from src.common.models import Chunk, DomainType

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Embedder Protocol
# -----------------------------------------------------------------------------


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Protocol contract for dense embedding generators."""

    @property
    def dimension(self) -> int:
        """Output dense vector dimension."""
        ...

    def embed_text(self, text: str) -> list[float]:
        """Generate dense vector embedding for single text string."""
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate dense vector embeddings for batch of texts."""
        ...

    def embed_chunk(self, chunk: Chunk) -> Chunk:
        """Compute embedding and assign to chunk.embedding, returning chunk."""
        ...

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Batch embed chunks and assign chunk.embedding in-place."""
        ...


# -----------------------------------------------------------------------------
# Deterministic Mock Embedder (for Testing & Offline Environments)
# -----------------------------------------------------------------------------


class MockEmbedder:
    """Deterministic, unit-normalized mock embedder for tests and offline execution.

    Generates reproducible float32 vectors based on the SHA-256 hash of the input text.
    """

    def __init__(
        self,
        dimension: int = 384,
        batch_size: int = 32,
        normalize: bool = True,
    ) -> None:
        self._dimension = dimension
        self.batch_size = batch_size
        self.normalize = normalize

    @property
    def dimension(self) -> int:
        """Output vector dimension."""
        return self._dimension

    def _generate_vector(self, text: str) -> list[float]:
        """Produce deterministic pseudo-random float vector of target dimension."""
        if not text:
            text = "__empty__"

        vec: list[float] = []
        # Expand hash iteratively to produce target number of dimensions
        round_idx = 0
        while len(vec) < self._dimension:
            digest = hashlib.sha256(f"{text}:{round_idx}".encode()).digest()
            num_ints = len(digest) // 4
            ints = struct.unpack(f"{num_ints}I", digest[: num_ints * 4])
            for val in ints:
                if len(vec) < self._dimension:
                    vec.append((val / 4294967295.0) * 2.0 - 1.0)
            round_idx += 1

        if self.normalize:
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 1e-9:
                vec = [x / norm for x in vec]
            else:
                vec = [1.0 / math.sqrt(self._dimension)] * self._dimension

        return vec

    def embed_text(self, text: str) -> list[float]:
        """Generate vector for single text."""
        return self._generate_vector(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate vectors for batch of texts."""
        return [self._generate_vector(t) for t in texts]

    def embed_chunk(self, chunk: Chunk) -> Chunk:
        """Embed single chunk and assign chunk.embedding."""
        chunk.embedding = self.embed_text(chunk.text)
        return chunk

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Embed multiple chunks in-place."""
        if not chunks:
            return chunks

        texts = [c.text for c in chunks]
        embeddings = self.embed_texts(texts)
        for chunk, emb in zip(chunks, embeddings, strict=False):
            chunk.embedding = emb
        return chunks


# -----------------------------------------------------------------------------
# Production Domain Embedder (SentenceTransformer)
# -----------------------------------------------------------------------------


class DomainEmbedder:
    """Production transformer embedding model with lazy loading and local weight caching."""

    def __init__(
        self,
        profile_name: str = "finance",
        model_name: str = "BAAI/bge-small-en-v1.5",
        dimension: int = 384,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.profile_name = profile_name
        self.model_name = model_name
        self._dimension = dimension
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._model: Any = None

    @property
    def dimension(self) -> int:
        """Output vector dimension."""
        return self._dimension

    def _get_model(self) -> Any:
        """Lazy load SentenceTransformer model weights upon first inference request."""
        if self._model is None:
            logger.info(
                "Loading embedding model '%s' for domain '%s' (cache_dir=%s)...",
                self.model_name,
                self.profile_name,
                self.cache_dir,
            )
            try:
                from sentence_transformers import SentenceTransformer

                cache_folder = str(self.cache_dir) if self.cache_dir else None
                self._model = SentenceTransformer(
                    self.model_name,
                    cache_folder=cache_folder,
                )
                logger.info(
                    "Successfully loaded embedding model '%s' (dim=%d)",
                    self.model_name,
                    self._dimension,
                )
            except Exception as exc:
                logger.error(
                    "Failed to load SentenceTransformer '%s': %s",
                    self.model_name,
                    exc,
                )
                raise RuntimeError(
                    f"Unable to load transformer model '{self.model_name}': {exc}"
                ) from exc

        return self._model

    def embed_text(self, text: str) -> list[float]:
        """Generate dense vector embedding for single text string."""
        model = self._get_model()
        cleaned_text = text if text and text.strip() else "__empty__"
        vec = model.encode(
            cleaned_text,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        return [float(x) for x in vec.tolist()]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate dense vector embeddings for batch of texts."""
        if not texts:
            return []

        model = self._get_model()
        cleaned = [t if t and t.strip() else "__empty__" for t in texts]
        embeddings = model.encode(
            cleaned,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        return [[float(x) for x in v] for v in embeddings.tolist()]

    def embed_chunk(self, chunk: Chunk) -> Chunk:
        """Embed single chunk and assign chunk.embedding."""
        chunk.embedding = self.embed_text(chunk.text)
        return chunk

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Embed list of chunks in-place with batching."""
        if not chunks:
            return chunks

        texts = [c.text for c in chunks]
        embeddings = self.embed_texts(texts)
        for chunk, emb in zip(chunks, embeddings, strict=False):
            chunk.embedding = emb
        return chunks


# -----------------------------------------------------------------------------
# Dynamic Embedding Registry (EMB-01)
# -----------------------------------------------------------------------------


class EmbeddingRegistry:
    """Dynamic Domain Embedding Registry managing runtime profiles and embedder instances."""

    def __init__(
        self,
        config: ModelRegistryConfig | None = None,
        settings: Settings | None = None,
        use_mock: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.use_mock = use_mock
        self._config = config or self._load_config()
        self._instances: dict[str, EmbedderProtocol] = {}

    def _load_config(self) -> ModelRegistryConfig:
        """Load domain model specifications from models.json or fallback to defaults."""
        try:
            return load_model_profiles()
        except Exception as exc:
            logger.warning("Failed to load models.json (%s); creating fallback config.", exc)
            return ModelRegistryConfig(
                default_profile="finance",
                profiles={
                    "finance": EmbeddingModelProfile(
                        name="finance",
                        model_name="BAAI/bge-small-en-v1.5",
                        dimension=384,
                        batch_size=32,
                    ),
                    "literature": EmbeddingModelProfile(
                        name="literature",
                        model_name="sentence-transformers/all-mpnet-base-v2",
                        dimension=768,
                        batch_size=16,
                    ),
                    "general": EmbeddingModelProfile(
                        name="general",
                        model_name="BAAI/bge-large-en-v1.5",
                        dimension=1024,
                        batch_size=16,
                    ),
                },
            )

    def get_profile(
        self, domain_or_profile: str | DomainType | None = None
    ) -> EmbeddingModelProfile:
        """Resolve EmbeddingModelProfile by domain or profile name."""
        key = str(domain_or_profile.value if isinstance(domain_or_profile, DomainType) else domain_or_profile or "").lower().strip()

        if key in self._config.profiles:
            return self._config.profiles[key]

        default_key = self._config.default_profile
        if default_key in self._config.profiles:
            return self._config.profiles[default_key]

        # Final fallback if config is empty
        return EmbeddingModelProfile(
            name="finance",
            model_name="BAAI/bge-small-en-v1.5",
            dimension=384,
            batch_size=32,
        )

    def list_profiles(self) -> dict[str, EmbeddingModelProfile]:
        """List all registered domain profiles."""
        return dict(self._config.profiles)

    def get_embedder(
        self, domain_or_profile: str | DomainType | None = None
    ) -> EmbedderProtocol:
        """Get or instantiate cached embedder for target domain."""
        profile = self.get_profile(domain_or_profile)
        cache_key = profile.name

        if cache_key not in self._instances:
            if self.use_mock:
                self._instances[cache_key] = MockEmbedder(
                    dimension=profile.dimension,
                    batch_size=profile.batch_size,
                    normalize=profile.normalize_embeddings,
                )
            else:
                cache_dir = self.settings.paths.model_cache_dir
                self._instances[cache_key] = DomainEmbedder(
                    profile_name=profile.name,
                    model_name=profile.model_name,
                    dimension=profile.dimension,
                    batch_size=profile.batch_size,
                    normalize_embeddings=profile.normalize_embeddings,
                    cache_dir=cache_dir,
                )

        return self._instances[cache_key]


# -----------------------------------------------------------------------------
# Global Singleton Provider
# -----------------------------------------------------------------------------

_GLOBAL_REGISTRY: EmbeddingRegistry | None = None


def get_embedding_registry(
    use_mock: bool = False,
    reload: bool = False,
) -> EmbeddingRegistry:
    """Dependency injection provider for EmbeddingRegistry."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None or reload:
        _GLOBAL_REGISTRY = EmbeddingRegistry(use_mock=use_mock)
    return _GLOBAL_REGISTRY

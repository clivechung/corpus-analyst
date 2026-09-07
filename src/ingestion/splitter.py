"""Secondary adaptive recursive token splitter and parent lineage tracking (ING-04).

Follows TREM-Python principles:
- Testable: Pure recursive splitting algorithms, deterministic token bounding, injected settings,
  and ChunkSplitterProtocol compliance.
- Readable: Fully typed function signatures, explicit delimiter hierarchies, and structured logging.
- Extensible: Protocol abstraction allowing alternative chunk splitters, pluggable token
  counters, and configurable delimiter hierarchies.
- Maintainable: Enforces strict chunk token limits (MAX_CHUNK_TOKENS=512) for downstream
  transformer embedding, sliding window context overlap (64 tokens), and complete
  parent-child lineage tracking for Lakehouse Parquet storage.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, runtime_checkable
from uuid import uuid4

from src.common.config import ChunkingSettings, get_settings
from src.common.models import Chunk
from src.ingestion.parser import estimate_token_count

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Splitter Protocol Contract (TREM: Extensible)
# -----------------------------------------------------------------------------


@runtime_checkable
class ChunkSplitterProtocol(Protocol):
    """Protocol for secondary chunk splitting strategies."""

    def split_chunk(self, chunk: Chunk) -> list[Chunk]:
        """Split a single chunk into size-compliant sub-chunks."""
        ...

    def split_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Process a sequence of chunks, splitting oversized elements."""
        ...


# -----------------------------------------------------------------------------
# Secondary Recursive Token Splitter Implementation (ING-04)
# -----------------------------------------------------------------------------


class RecursiveTokenSplitter(ChunkSplitterProtocol):
    """Adaptive recursive token splitter enforcing strict upper bounds on chunk sizes.

    Features:
    - Bounding chunks to MAX_CHUNK_TOKENS (default: 512 tokens / ~2,000 chars).
    - Preserving semantic continuity via sliding window overlap (default: 64 tokens).
    - Ordered delimiter recursion: paragraphs (\\n\\n), lines (\\n), sentences (. ),
      words ( ), and unbroken character slicing fallback.
    - Full parent-child lineage tracking (parent_chunk_id, sub_chunk_index, total_sub_chunks).
    - Table-aware splitting preserving is_table=True and table_id lineage.
    """

    GENERIC_DELIMITERS = ["\n\n", "\n", ". ", " "]
    TABLE_DELIMITERS = ["</tr>\n", "</tr>", "\n\n", "\n", ". ", " "]

    def __init__(
        self,
        settings: ChunkingSettings | None = None,
        token_counter: Callable[[str], int] | None = None,
        delimiters: list[str] | None = None,
    ) -> None:
        """Initialize recursive token splitter.

        Args:
            settings: ChunkingSettings instance with max_chunk_tokens and chunk_overlap_tokens.
            token_counter: Callable returning integer token count for a text string.
            delimiters: Optional custom delimiter hierarchy.
        """
        if settings is not None:
            self.settings = settings
        else:
            try:
                self.settings = get_settings().chunking
            except Exception:
                self.settings = ChunkingSettings()

        self.token_counter = token_counter or estimate_token_count
        self.delimiters = delimiters or self.GENERIC_DELIMITERS

    def _split_text_with_delimiters(
        self,
        text: str,
        delimiters: list[str],
        max_tokens: int,
        overlap_tokens: int,
        max_chars: int,
    ) -> list[str]:
        """Recursively partition text down the delimiter hierarchy."""
        if not text or not text.strip():
            return []

        # If text already fits within token and character bounds, keep intact
        if self.token_counter(text) <= max_tokens and len(text) <= max_chars:
            return [text.strip()]

        # Find first delimiter present in text
        chosen_delim: str | None = None
        chosen_idx: int = -1
        for idx, delim in enumerate(delimiters):
            if delim in text:
                chosen_delim = delim
                chosen_idx = idx
                break

        # Fallback: unbroken text with no matching delimiters -> character slicing
        if chosen_delim is None:
            step = max(1, min(max_chars, max_tokens * 3))
            chunks: list[str] = []
            start = 0
            while start < len(text):
                end = min(len(text), start + step)
                slice_str = text[start:end].strip()
                if slice_str:
                    chunks.append(slice_str)
                if end >= len(text):
                    break
                advance = max(1, step - max(0, overlap_tokens * 3))
                start += advance
            return chunks

        # Split by chosen delimiter
        raw_splits = text.split(chosen_delim)
        remaining_delimiters = delimiters[chosen_idx + 1 :]

        # Recursively process oversized units
        units: list[str] = []
        for s in raw_splits:
            s_clean = s.strip()
            if not s_clean:
                continue
            if self.token_counter(s_clean) <= max_tokens and len(s_clean) <= max_chars:
                units.append(s_clean)
            else:
                sub_units = self._split_text_with_delimiters(
                    s_clean,
                    remaining_delimiters,
                    max_tokens,
                    overlap_tokens,
                    max_chars,
                )
                units.extend(sub_units)

        # Merge units with chosen_delim
        chunks: list[str] = []
        current_units: list[str] = []
        current_tokens = 0
        sep = chosen_delim

        for u in units:
            u_tokens = self.token_counter(u)
            sep_tokens = self.token_counter(sep) if current_units else 0

            candidate_tokens = current_tokens + u_tokens + sep_tokens
            candidate_chars = (
                sum(len(x) for x in current_units) + len(sep) * len(current_units) + len(u)
                if current_units
                else len(u)
            )

            if (candidate_tokens > max_tokens or candidate_chars > max_chars) and current_units:
                chunk_text = sep.join(current_units).strip()
                if chunk_text:
                    chunks.append(chunk_text)

                if overlap_tokens <= 0:
                    current_units = []
                    current_tokens = 0
                else:
                    while current_units:
                        curr_text = sep.join(current_units)
                        if self.token_counter(curr_text) <= overlap_tokens:
                            break
                        current_units.pop(0)

                    current_tokens = self.token_counter(sep.join(current_units)) if current_units else 0

            current_units.append(u)
            current_tokens = self.token_counter(sep.join(current_units))

        if current_units:
            chunk_text = sep.join(current_units).strip()
            if chunk_text:
                chunks.append(chunk_text)

        return chunks

    def split_text(
        self,
        text: str,
        max_tokens: int | None = None,
        overlap_tokens: int | None = None,
        is_table: bool = False,
    ) -> list[str]:
        """Recursively partition text into chunks bounded by max_tokens with sliding window overlap.

        Args:
            text: Text to partition.
            max_tokens: Maximum tokens per chunk (defaults to settings.max_chunk_tokens).
            overlap_tokens: Sliding window overlap tokens (defaults to settings.chunk_overlap_tokens).
            is_table: Whether text represents tabular markup.

        Returns:
            List of string chunks satisfying the token upper bound.
        """
        if not text or not text.strip():
            return []

        limit = max_tokens if max_tokens is not None else self.settings.max_chunk_tokens
        overlap = overlap_tokens if overlap_tokens is not None else self.settings.chunk_overlap_tokens
        max_chars = self.settings.max_characters

        # Quick path: if whole text fits in token and character limits, return as single chunk
        if self.token_counter(text) <= limit and len(text) <= max_chars:
            return [text]

        delimiters = self.TABLE_DELIMITERS if is_table else self.delimiters
        return self._split_text_with_delimiters(text, delimiters, limit, overlap, max_chars)

    def split_chunk(self, chunk: Chunk) -> list[Chunk]:
        """Evaluate a Chunk against MAX_CHUNK_TOKENS and split if oversized.

        If chunk token count <= max_chunk_tokens:
            Returns the chunk unmodified in a single-element list.
        If chunk token count > max_chunk_tokens:
            Emits a list of child Chunks with parent lineage tracking:
            - parent_chunk_id set to parent chunk UUID
            - sub_chunk_index and total_sub_chunks in metadata
            - table_id and is_table preserved for tabular chunks
            - all child chunks strictly <= max_chunk_tokens

        Args:
            chunk: Input Chunk model.

        Returns:
            List of size-compliant Chunk models.
        """
        if chunk.token_count is None:
            chunk.token_count = self.token_counter(chunk.text)

        if chunk.token_count <= self.settings.max_chunk_tokens and len(chunk.text) <= self.settings.max_characters:
            return [chunk]

        text_slices = self.split_text(
            chunk.text,
            max_tokens=self.settings.max_chunk_tokens,
            overlap_tokens=self.settings.chunk_overlap_tokens,
            is_table=chunk.is_table,
        )

        if len(text_slices) <= 1:
            chunk.token_count = self.token_counter(chunk.text)
            return [chunk]

        total_sub_chunks = len(text_slices)
        child_chunks: list[Chunk] = []

        for idx, slice_text in enumerate(text_slices):
            child_id = uuid4()
            child_tokens = self.token_counter(slice_text)

            child_metadata: dict[str, Any] = dict(chunk.metadata)
            child_metadata["parent_chunk_id"] = str(chunk.chunk_id)
            child_metadata["sub_chunk_index"] = idx
            child_metadata["total_sub_chunks"] = total_sub_chunks
            child_metadata["is_split"] = True
            child_metadata["token_count"] = child_tokens

            if chunk.is_table:
                table_id = str(chunk.metadata.get("table_id", chunk.chunk_id))
                child_metadata["table_id"] = table_id
                child_metadata["is_table_fragment"] = True
                child_metadata["table_html"] = slice_text

            child = Chunk(
                chunk_id=child_id,
                doc_id=chunk.doc_id,
                domain=chunk.domain,
                source_filename=chunk.source_filename,
                form_type=chunk.form_type,
                filing_date=chunk.filing_date,
                section=chunk.section,
                is_table=chunk.is_table,
                text=slice_text,
                embedding=None,
                parent_chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                token_count=child_tokens,
                metadata=child_metadata,
            )
            child_chunks.append(child)

        logger.debug(
            "Split oversized chunk %s (%d tokens) into %d sub-chunks for %s",
            chunk.chunk_id,
            chunk.token_count,
            len(child_chunks),
            chunk.source_filename,
        )
        return child_chunks

    def split_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Batch process a list of chunks, splitting any that exceed max_chunk_tokens.

        Args:
            chunks: Sequence of input Chunks.

        Returns:
            Flat list of size-compliant Chunks.
        """
        bounded: list[Chunk] = []
        for chunk in chunks:
            bounded.extend(self.split_chunk(chunk))
        return bounded


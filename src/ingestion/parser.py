"""Structural document partitioning and table layout preservation engine (ING-03).

Follows TREM-Python principles:
- Testable: Pure parsing functions, decoupled section tracking, injected settings,
  and clean DocumentProcessorProtocol compliance.
- Readable: Fully annotated type signatures, explicit regex section parsers,
  and structured logging.
- Extensible: Multi-format dispatch (HTML, PDF, TXT, JSON) with hooks for
  Phase 4 ING-04 recursive token splitting and Phase 5 embedding.
- Maintainable: Verbatim HTML table preservation with table flags, deterministic
  token bounds, companion sidecar propagation, and domain exception handling.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.common.config import Settings, get_settings
from src.common.models import (
    Chunk,
    DocumentMetadata,
    DomainType,
    FormType,
    IngestionStatus,
)
from src.ingestion.lifecycle import DocumentProcessorProtocol, IngestionResult

if TYPE_CHECKING:
    from src.ingestion.splitter import ChunkSplitterProtocol

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Domain Exceptions & Utility Functions
# -----------------------------------------------------------------------------


class DocumentParsingError(Exception):
    """Raised when document parsing fails or file content is invalid/unreadable."""

    pass


def estimate_token_count(text: str) -> int:
    """Calculate deterministic token count estimate for chunk text.

    Uses word and punctuation tokenization matching typical BPE/WordPiece token density.

    Args:
        text: Input string to tokenize.

    Returns:
        Integer count of estimated tokens (0 for empty/whitespace-only strings).
    """
    if not text or not text.strip():
        return 0
    tokens = re.findall(r"\w+|[^\w\s]", text)
    return len(tokens)


# -----------------------------------------------------------------------------
# Section Hierarchy Tracker
# -----------------------------------------------------------------------------


class SectionTracker:
    """Stateful tracker for document section hierarchy and context propagation.

    Detects SEC EDGAR standard items (10-K, 10-Q) and literature chapters,
    cascading the active section to child narrative and tabular elements.
    """

    SEC_ITEM_MAP: dict[str, str] = {
        "1": "Item 1 - Business",
        "1A": "Item 1A - Risk Factors",
        "1B": "Item 1B - Unresolved Staff Comments",
        "2": "Item 2 - Properties",
        "3": "Item 3 - Legal Proceedings",
        "4": "Item 4 - Mine Safety Disclosures",
        "5": "Item 5 - Market for Registrant's Common Equity",
        "6": "Item 6 - [Reserved]",
        "7": "Item 7 - Management's Discussion and Analysis",
        "7A": "Item 7A - Quantitative and Qualitative Disclosures",
        "8": "Item 8 - Financial Statements",
        "9": "Item 9 - Changes in and Disagreements with Accountants",
        "9A": "Item 9A - Controls and Procedures",
        "9B": "Item 9B - Other Information",
        "9C": "Item 9C - Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
        "10": "Item 10 - Directors, Executive Officers and Corporate Governance",
        "11": "Item 11 - Executive Compensation",
        "12": "Item 12 - Security Ownership of Certain Beneficial Owners",
        "13": "Item 13 - Certain Relationships and Related Transactions",
        "14": "Item 14 - Principal Accountant Fees and Services",
        "15": "Item 15 - Exhibits and Financial Statement Schedules",
        "16": "Item 16 - Form 10-K Summary",
    }

    SEC_ITEM_PATTERN = re.compile(
        r"^\s*item\s+([0-9]{1,2}[A-Za-z]?)\.?\s*[-–—:]?\s*(.*?)(?=\.|\n|$)",
        re.IGNORECASE,
    )
    PART_PATTERN = re.compile(r"^\s*part\s+([IVXLCDM]+)\b", re.IGNORECASE)
    CHAPTER_PATTERN = re.compile(
        r"^\s*chapter\s+(\d+|[A-Za-z]+)[:\s\-\.]*(.*)",
        re.IGNORECASE,
    )

    def __init__(self, initial_section: str = "General") -> None:
        self._current_section = initial_section

    @property
    def current_section(self) -> str:
        """Active section context."""
        return self._current_section

    def get_active_section(self) -> str:
        """Return the current cascaded section name."""
        return self._current_section

    def update(self, text: str) -> str | None:
        """Inspect element text for section headings.

        If a new section or chapter heading is detected, updates internal state
        and returns the normalized section name. Otherwise returns None.

        Args:
            text: Text content of the document element.

        Returns:
            Normalized section name string if detected, else None.
        """
        if not text:
            return None

        clean_text = text.strip()

        # 1. SEC Item Check
        sec_match = self.SEC_ITEM_PATTERN.match(clean_text)
        if sec_match:
            item_num = sec_match.group(1).upper()
            normalized = self.SEC_ITEM_MAP.get(
                item_num,
                f"Item {item_num} - {sec_match.group(2).strip()}" if sec_match.group(2).strip() else f"Item {item_num}",
            )
            self._current_section = normalized
            return normalized

        # 2. SEC Part Check
        part_match = self.PART_PATTERN.match(clean_text)
        if part_match:
            normalized = f"Part {part_match.group(1).upper()}"
            self._current_section = normalized
            return normalized

        # 3. Literature Chapter Check
        chap_match = self.CHAPTER_PATTERN.match(clean_text)
        if chap_match:
            ch_num = chap_match.group(1)
            title = chap_match.group(2).strip()
            normalized = f"Chapter {ch_num} - {title}" if title else f"Chapter {ch_num}"
            self._current_section = normalized
            return normalized

        return None


# -----------------------------------------------------------------------------
# Document Parser Engine (ING-03)
# -----------------------------------------------------------------------------


class DocumentParser(DocumentProcessorProtocol):
    """Structural document parser implementing unstructured document partitioning.

    Satisfies DocumentProcessorProtocol for seamless integration with LifecycleManager.
    Extracts headings, maintains section hierarchies, and preserves verbatim HTML table markup.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        splitter: ChunkSplitterProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if splitter is not None:
            self.splitter: ChunkSplitterProtocol | None = splitter
        else:
            from src.ingestion.splitter import RecursiveTokenSplitter

            self.splitter = RecursiveTokenSplitter(settings=self.settings.chunking)

    def _resolve_metadata(self, file_path: Path, metadata: DocumentMetadata | None = None) -> DocumentMetadata:
        """Resolve companion .meta.json sidecar or generate deterministic metadata envelope."""
        if metadata is not None:
            return metadata

        # Check sidecars
        sidecar_candidates = [
            file_path.with_name(f"{file_path.name}.meta.json"),
            file_path.with_name(f"{file_path.stem}.meta.json"),
        ]
        for candidate in sidecar_candidates:
            if candidate.is_file():
                try:
                    with open(candidate, encoding="utf-8") as f:
                        data = json.load(f)
                        return DocumentMetadata(**data)
                except Exception as exc:
                    logger.warning("Failed to parse sidecar at %s: %s", candidate, exc)

        # Fallback deterministic document metadata
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            doc_id = hashlib.sha256(content).hexdigest()[:16]
        except Exception:
            doc_id = f"doc-{uuid4().hex[:12]}"

        # Infer form type from filename
        upper_name = file_path.name.upper()
        if "10-K" in upper_name:
            form_type = FormType.SEC_10K
        elif "10-Q" in upper_name:
            form_type = FormType.SEC_10Q
        elif "8-K" in upper_name:
            form_type = FormType.SEC_8K
        elif file_path.suffix.lower() == ".txt" or "BOOK" in upper_name:
            form_type = FormType.BOOK
        else:
            form_type = FormType.MISC

        domain = self.settings.app.default_domain or DomainType.FINANCE

        return DocumentMetadata(
            doc_id=doc_id,
            source_filename=file_path.name,
            domain=domain,
            form_type=form_type,
        )

    def parse(self, file_path: Path, metadata: DocumentMetadata | None = None) -> list[Chunk]:
        """Partition a document into a sequence of structural Chunk objects.

        Preserves:
        - Section hierarchy via SectionTracker.
        - Verbatim HTML table representation for tabular elements with is_table = True.
        - Lineage metadata, token counts, and sidecar attributes.

        Args:
            file_path: Path to document file.
            metadata: Optional DocumentMetadata envelope.

        Returns:
            List of validated Chunk instances.

        Raises:
            DocumentParsingError: If file is missing, empty, or partition fails.
        """
        if not file_path.is_file():
            raise DocumentParsingError(f"Document file not found: {file_path}")

        file_size = file_path.stat().st_size
        if file_size == 0:
            raise DocumentParsingError(f"Document file is empty (0 bytes): {file_path}")

        doc_meta = self._resolve_metadata(file_path, metadata)
        tracker = SectionTracker()
        suffix = file_path.suffix.lower()

        try:
            raw_elements = self._partition_file(file_path, suffix)
        except DocumentParsingError:
            raise
        except Exception as exc:
            raise DocumentParsingError(f"Partitioning failed for {file_path.name}: {exc}") from exc

        if not raw_elements:
            raise DocumentParsingError(f"No parseable content extracted from: {file_path.name}")

        chunks: list[Chunk] = []
        for element in raw_elements:
            el_text = getattr(element, "text", "") or ""
            category = getattr(element, "category", type(element).__name__)
            meta_dict = element.metadata.to_dict() if hasattr(element, "metadata") and hasattr(element.metadata, "to_dict") else {}

            # Check if element triggers section header update
            tracker.update(el_text)
            current_sec = tracker.get_active_section()

            # Determine table nature and layout
            is_table = (
                category == "Table"
                or type(element).__name__ == "Table"
                or "text_as_html" in meta_dict
            )

            if is_table:
                # Verbatim HTML table preservation
                table_html = meta_dict.get("text_as_html")
                if not table_html and "<table" in el_text.lower():
                    table_html = el_text

                chunk_text = table_html if table_html else el_text
                chunk_meta: dict[str, Any] = {
                    "element_type": "Table",
                    "category": category,
                }
                if table_html:
                    chunk_meta["table_html"] = table_html
            else:
                if not el_text.strip():
                    continue
                chunk_text = el_text.strip()
                chunk_meta = {
                    "element_type": category,
                    "category": category,
                }

            page_number = meta_dict.get("page_number")
            token_count = estimate_token_count(chunk_text)
            chunk_meta["token_count"] = token_count

            chunk = Chunk(
                chunk_id=uuid4(),
                doc_id=doc_meta.doc_id,
                domain=doc_meta.domain,
                source_filename=file_path.name,
                form_type=doc_meta.form_type,
                filing_date=doc_meta.filing_date,
                section=current_sec,
                is_table=is_table,
                text=chunk_text,
                page_number=page_number,
                token_count=token_count,
                metadata=chunk_meta,
            )
            chunks.append(chunk)

        if not chunks:
            raise DocumentParsingError(f"No non-empty chunks could be constructed from: {file_path.name}")

        # Secondary adaptive splitting (ING-04) strictly bounding chunks to max_chunk_tokens
        if self.splitter is not None:
            chunks = self.splitter.split_chunks(chunks)

        logger.info(
            "Successfully parsed %s into %d chunks (tables: %d, section: %s)",
            file_path.name,
            len(chunks),
            sum(1 for c in chunks if c.is_table),
            tracker.get_active_section(),
        )
        return chunks

    def _partition_file(self, file_path: Path, suffix: str) -> list[Any]:
        """Dispatch document parsing to the appropriate unstructured partitioner."""
        if suffix in (".htm", ".html"):
            from unstructured.partition.html import partition_html
            return partition_html(filename=str(file_path))

        elif suffix == ".pdf":
            from unstructured.partition.pdf import partition_pdf
            try:
                return partition_pdf(filename=str(file_path), strategy="fast")
            except Exception:
                from unstructured.partition.auto import partition
                return partition(filename=str(file_path))

        elif suffix == ".txt":
            from unstructured.partition.text import partition_text
            return partition_text(filename=str(file_path))

        elif suffix == ".json":
            # For JSON, parse structured records and build text elements
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            from unstructured.documents.elements import NarrativeText, Title

            elements: list[Any] = []
            if isinstance(data, dict):
                title = data.get("title") or data.get("name")
                if title:
                    elements.append(Title(text=str(title)))
                content = data.get("content") or data.get("text") or data.get("body")
                if content:
                    elements.append(NarrativeText(text=str(content)))
                else:
                    elements.append(NarrativeText(text=json.dumps(data, indent=2)))
            elif isinstance(data, list):
                for item in data:
                    elements.append(NarrativeText(text=str(item) if not isinstance(item, dict) else json.dumps(item)))
            else:
                elements.append(NarrativeText(text=str(data)))
            return elements

        else:
            # Fallback to auto partitioner
            from unstructured.partition.auto import partition
            return partition(filename=str(file_path))

    def process(self, file_path: Path, metadata: DocumentMetadata | None = None) -> IngestionResult:
        """Process document conforming to DocumentProcessorProtocol.

        Parses the document, calculates metrics, and returns IngestionResult envelope.

        Args:
            file_path: File to parse.
            metadata: Optional DocumentMetadata.

        Returns:
            IngestionResult lifecycle envelope.
        """
        start_time = time.perf_counter()
        try:
            chunks = self.parse(file_path, metadata)
            doc_meta = self._resolve_metadata(file_path, metadata)
            chunk_count = len(chunks)
            token_total = sum(c.token_count or 0 for c in chunks)
            elapsed = time.perf_counter() - start_time

            return IngestionResult(
                success=True,
                status=IngestionStatus.COMPLETED,
                metadata=doc_meta,
                chunk_count=chunk_count,
                token_total=token_total,
                duration_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            logger.error("Processing failed for %s: %s", file_path.name, exc)
            return IngestionResult(
                success=False,
                status=IngestionStatus.FAILED,
                metadata=metadata,
                chunk_count=0,
                token_total=0,
                duration_seconds=elapsed,
                error_message=str(exc),
            )

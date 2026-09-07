"""Shared Pydantic data schemas and contracts for corpus-analyst platform.

Follows TREM principles:
- Testable: Pure data contracts with deterministic serialization and validation.
- Readable: Fully annotated fields with explicit documentation.
- Extensible: Typed enums and extensible metadata dictionary payloads.
- Maintainable: Direct conversion utilities (e.g. to_parquet_dict) to guarantee
  lakehouse schema compliance across ingestion, DuckDB query engine, and UI services.
"""

from __future__ import annotations

import json
from datetime import date
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------
# Domain & Document Type Enums
# -----------------------------------------------------------------------------


class DomainType(str, Enum):
    """Supported operational domain categories for corpus data."""

    FINANCE = "finance"
    LITERATURE = "literature"
    GENERAL = "general"


class FormType(str, Enum):
    """Document classification types (SEC EDGAR filings, books, or generic)."""

    SEC_10K = "10-K"
    SEC_10Q = "10-Q"
    SEC_8K = "8-K"
    BOOK = "BOOK"
    MISC = "MISC"


class LLMProvider(str, Enum):
    """Supported inference LLM providers."""

    GEMINI = "gemini"
    OLLAMA = "ollama"


class IngestionStatus(str, Enum):
    """Document lifecycle processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# -----------------------------------------------------------------------------
# Ingestion & Lakehouse Storage Models
# -----------------------------------------------------------------------------


class DocumentMetadata(BaseModel):
    """Metadata envelope describing a raw ingested document before chunking."""

    model_config = ConfigDict(use_enum_values=True)

    doc_id: str = Field(description="Deterministic document identifier (SHA256 hash or SEC accession number)")
    source_filename: str = Field(description="Original filename or SEC Edgar identifier")
    domain: DomainType | str = Field(default=DomainType.FINANCE, description="Target corpus domain")
    form_type: FormType | str = Field(default=FormType.MISC, description="Form or document classification")
    filing_date: date | None = Field(default=None, description="Filing or publication date")
    company_name: str | None = Field(default=None, description="Reporting entity / company name")
    ticker: str | None = Field(default=None, description="Stock ticker symbol (e.g. NVDA, AAPL)")
    total_pages: int | None = Field(default=None, description="Total document page count")
    extra: dict[str, Any] = Field(default_factory=dict, description="Additional arbitrary document attributes")


class Chunk(BaseModel):
    """The fundamental unit of indexing, vector embedding, and lakehouse storage.

    Matches Section 4.3 of the PRD specification for Hive-partitioned Parquet storage.
    """

    model_config = ConfigDict(use_enum_values=True)

    chunk_id: UUID = Field(default_factory=uuid4, description="Unique chunk UUIDv4")
    doc_id: str = Field(description="Foreign key back to parent document")
    domain: DomainType | str = Field(description="Target domain profile key")
    source_filename: str = Field(description="Original document filename")
    form_type: FormType | str = Field(default=FormType.MISC, description="Document type classification")
    filing_date: date | None = Field(default=None, description="Document filing date used in Hive partition/pruning")
    section: str = Field(default="General", description="Document section or header (e.g. Item 1A, Item 7)")
    is_table: bool = Field(default=False, description="Flag indicating whether chunk represents tabular data")
    text: str = Field(description="Cleaned text content of the chunk")
    embedding: list[float] | None = Field(default=None, description="Dense vector embedding array")
    parent_chunk_id: UUID | None = Field(default=None, description="Lineage link to parent chunk if recursively split")
    page_number: int | None = Field(default=None, description="Page number where element appears")
    token_count: int | None = Field(default=None, description="Calculated token count of chunk text")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary bounding box / structural metadata")

    def to_parquet_dict(self) -> dict[str, Any]:
        """Convert chunk into a dictionary matching the Lakehouse Parquet schema.

        Schema specified in PRD Section 4.3:
        - chunk_id: STRING (UUIDv4)
        - doc_id: STRING
        - domain: STRING
        - source_filename: STRING
        - form_type: STRING
        - filing_date: DATE32
        - section: STRING
        - is_table: BOOLEAN
        - text: STRING
        - embedding: LIST<FLOAT>
        - metadata_json: STRING
        """
        # Pack secondary lineage and extra attributes into metadata_json
        meta_payload = dict(self.metadata)
        if self.page_number is not None:
            meta_payload["page_number"] = self.page_number
        if self.token_count is not None:
            meta_payload["token_count"] = self.token_count
        if self.parent_chunk_id is not None:
            meta_payload["parent_chunk_id"] = str(self.parent_chunk_id)

        form_type_str = self.form_type.value if isinstance(self.form_type, Enum) else str(self.form_type)
        domain_str = self.domain.value if isinstance(self.domain, Enum) else str(self.domain)

        return {
            "chunk_id": str(self.chunk_id),
            "doc_id": self.doc_id,
            "domain": domain_str,
            "source_filename": self.source_filename,
            "form_type": form_type_str,
            "filing_date": self.filing_date,
            "section": self.section,
            "is_table": self.is_table,
            "text": self.text,
            "embedding": self.embedding,
            "metadata_json": json.dumps(meta_payload),
        }


class DeadLetterRecord(BaseModel):
    """Dead-letter record schema logged when document processing fails."""

    model_config = ConfigDict(use_enum_values=True)

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when error occurred",
    )
    source_filename: str = Field(description="Name of the file that failed processing")
    file_size_bytes: int = Field(ge=0, description="Size of the file in bytes")
    error_type: str = Field(description="Exception class name")
    error_message: str = Field(description="Human-readable error description")
    stack_trace: str = Field(description="Full exception stack trace")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extracted or context metadata")


class IngestionSummary(BaseModel):
    """Execution summary emitted after document lifecycle processing completes."""

    model_config = ConfigDict(use_enum_values=True)

    file_path: str = Field(description="Path to processed file")
    status: IngestionStatus | str = Field(description="Final processing lifecycle status")
    duration_seconds: float = Field(ge=0.0, description="Processing duration in seconds")
    chunk_count: int = Field(default=0, ge=0, description="Total chunks generated")
    token_total: int = Field(default=0, ge=0, description="Total tokens across generated chunks")
    parquet_paths: list[str] = Field(
        default_factory=list, description="List of generated Lakehouse Parquet file paths"
    )
    error_message: str | None = Field(default=None, description="Error detail if failed")



# -----------------------------------------------------------------------------
# Query & Retrieval Models
# -----------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Payload contract for query and search endpoints."""

    model_config = ConfigDict(use_enum_values=True)

    question: str = Field(min_length=1, description="Natural language query or question")
    domain: DomainType | str = Field(default=DomainType.FINANCE, description="Target domain for vector search")
    top_k: int = Field(default=5, ge=1, le=100, description="Maximum number of candidate chunks to retrieve")
    form_type: FormType | str | None = Field(default=None, description="Optional filter by document form type")
    start_date: date | None = Field(default=None, description="Filter documents filed on or after this date")
    end_date: date | None = Field(default=None, description="Filter documents filed on or before this date")
    is_table_only: bool = Field(default=False, description="Whether to restrict search strictly to tabular chunks")
    similarity_threshold: float = Field(
        default=0.0, ge=-1.0, le=1.0, description="Minimum cosine similarity cutoff (-1.0 to 1.0)"
    )


class RetrievedContextChunk(BaseModel):
    """Candidate context chunk retrieved from DuckDB vector scan."""

    chunk_id: str = Field(description="Retrieved chunk UUID string")
    source_filename: str = Field(description="Source filename")
    section: str = Field(description="Document section or header")
    text: str = Field(description="Chunk text excerpt")
    is_table: bool = Field(default=False, description="Tabular flag")
    similarity_score: float = Field(description="Cosine similarity score (0.0 to 1.0)")
    form_type: str | None = Field(default=None, description="Document classification")
    filing_date: date | None = Field(default=None, description="Document filing date")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extracted chunk metadata")


class Citation(BaseModel):
    """Traceable citation attribution for grounded generation."""

    source_filename: str = Field(description="Name of the source filing or document")
    section: str = Field(description="Section heading")
    chunk_id: str = Field(description="Associated chunk ID")
    similarity_score: float = Field(description="Retrieval similarity score")
    excerpt: str = Field(description="Exact excerpt grounding the answer")


class QueryResponse(BaseModel):
    """Complete response contract from Query Engine API."""

    question: str = Field(description="Original user question")
    answer: str = Field(description="LLM synthesized response or agent answer")
    domain: str = Field(description="Domain used for retrieval")
    retrieved_chunks: list[RetrievedContextChunk] = Field(
        default_factory=list, description="Ranked context chunks from DuckDB vector search"
    )
    citations: list[Citation] = Field(
        default_factory=list, description="Explicit traceable citations backing the answer"
    )
    latency_ms: float = Field(default=0.0, description="End-to-end request latency in milliseconds")
    model_used: str = Field(default="", description="Inference model identifier")


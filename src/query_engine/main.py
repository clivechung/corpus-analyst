"""FastAPI Query Engine Service for DuckDB Lakehouse RAG Platform (QRY-01, QRY-02, QRY-03).

Follows TREM-Python principles:
- Testable: Dependency injection of Settings, DuckDBLakehouseClient, and EmbeddingRegistry
  via FastAPI Depends() for easy test overrides and mock substitution.
- Readable: Fully type-hinted endpoint signatures with explicit Pydantic request/response models.
- Extensible: Clean separation between raw vector search (/api/v1/search) and grounded
  citation synthesis (/api/v1/query).
- Maintainable: Detailed operational logging, latency metrics, and lakehouse telemetry probes.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status

from src.common.config import Settings, get_settings
from src.common.models import (
    Citation,
    EmbedRequest,
    EmbedResponse,
    QueryRequest,
    QueryResponse,
    RetrievedContextChunk,
    SQLQueryRequest,
    SQLQueryResponse,
)
from src.ingestion.embedder import EmbeddingRegistry, get_embedding_registry
from src.query_engine.duckdb_client import DuckDBLakehouseClient, get_duckdb_client

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Corpus Analyst Query Engine",
    version="0.1.0",
    description="Stateless DuckDB vector lakehouse retrieval and LLM synthesis service.",
)


def get_app_settings() -> Settings:
    """Dependency provider for application settings (TREM: Testable)."""
    return get_settings()


def get_query_duckdb_client(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DuckDBLakehouseClient:
    """Dependency provider for DuckDBLakehouseClient."""
    return get_duckdb_client(settings=settings)


def get_query_embedding_registry() -> EmbeddingRegistry:
    """Dependency provider for EmbeddingRegistry."""
    return get_embedding_registry()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DuckDBDep = Annotated[DuckDBLakehouseClient, Depends(get_query_duckdb_client)]
RegistryDep = Annotated[EmbeddingRegistry, Depends(get_query_embedding_registry)]


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["System"])
def liveness_probe() -> dict[str, str]:
    """Kubernetes and Docker Compose liveness probe endpoint."""
    return {"status": "ok", "service": "query-engine"}


@app.get("/api/v1/health", status_code=status.HTTP_200_OK, tags=["System"])
def detailed_health(
    settings: SettingsDep,
    duckdb_client: DuckDBDep,
) -> dict[str, Any]:
    """Service health inspection endpoint with active configuration and lake summary."""
    lake_stats = duckdb_client.get_lake_stats()
    return {
        "status": "ok",
        "service": "query-engine",
        "version": "0.1.0",
        "environment": settings.app.env,
        "default_domain": settings.app.default_domain,
        "total_parquet_files": lake_stats.get("total_parquet_files", 0),
        "total_size_bytes": lake_stats.get("total_size_bytes", 0),
        "domains": lake_stats.get("domains", []),
    }


@app.post(
    "/api/v1/search",
    response_model=list[RetrievedContextChunk],
    status_code=status.HTTP_200_OK,
    tags=["Query"],
)
def search_chunks(
    request: QueryRequest,
    settings: SettingsDep,
    duckdb_client: DuckDBDep,
    registry: RegistryDep,
) -> list[RetrievedContextChunk]:
    """Vector similarity and metadata SQL search returning candidate chunks without synthesis."""
    target_domain = request.domain or settings.app.default_domain
    logger.info(
        "Executing candidate chunk search: domain=%s top_k=%d question='%s'",
        target_domain,
        request.top_k,
        request.question,
    )

    embedder = registry.get_embedder(target_domain)
    query_vec = embedder.embed_text(request.question)

    return duckdb_client.search(request, query_vector=query_vec)


@app.post(
    "/api/v1/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Query"],
)
def execute_query(
    request: QueryRequest,
    settings: SettingsDep,
    duckdb_client: DuckDBDep,
    registry: RegistryDep,
) -> QueryResponse:
    """Execute vector retrieval, citation attribution, and grounded synthesis over DuckDB lakehouse."""
    start_time = time.perf_counter()
    target_domain = request.domain or settings.app.default_domain

    logger.info(
        "Executing query and synthesis: domain=%s question='%s'",
        target_domain,
        request.question,
    )

    embedder = registry.get_embedder(target_domain)
    query_vec = embedder.embed_text(request.question)

    chunks = duckdb_client.search(request, query_vector=query_vec)

    # Build traceable citations
    citations: list[Citation] = []
    for chunk in chunks:
        excerpt = chunk.text[:280].strip()
        if len(chunk.text) > 280:
            excerpt += "..."
        citations.append(
            Citation(
                source_filename=chunk.source_filename,
                section=chunk.section,
                chunk_id=chunk.chunk_id,
                similarity_score=round(chunk.similarity_score, 4),
                excerpt=excerpt,
            )
        )

    # Grounded answer synthesis
    if chunks:
        source_names = list(dict.fromkeys(c.source_filename for c in chunks))
        sources_str = ", ".join(source_names[:3])
        bullet_points = "\n".join(
            f"• [{c.section} // Score: {c.similarity_score:.4f}]: {c.text[:200].strip()}..."
            for c in chunks[:3]
        )
        answer = (
            f"Grounded analysis based on {len(chunks)} retrieved context chunks from {sources_str}:\n\n"
            f"{bullet_points}\n\n"
            f"Primary attribution grounded in {chunks[0].source_filename} ({chunks[0].section})."
        )
    else:
        answer = (
            f"No relevant context chunks were located in the lakehouse for domain '{target_domain}' "
            "matching the query and active metadata filters."
        )

    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    model_used = f"duckdb-vector-{target_domain}"

    return QueryResponse(
        question=request.question,
        answer=answer,
        domain=str(target_domain),
        retrieved_chunks=chunks,
        citations=citations,
        latency_ms=latency_ms,
        model_used=model_used,
    )


@app.post(
    "/api/v1/sql",
    response_model=SQLQueryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Query"],
)
def execute_sql_query(
    request: SQLQueryRequest,
    duckdb_client: DuckDBDep,
) -> SQLQueryResponse:
    """Execute read-only SQL query over DuckDB lakehouse."""
    start_time = time.perf_counter()
    try:
        cols, rows = duckdb_client.execute_sql(request.query, params=request.params or None)
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        serialized_rows = [[item for item in r] for r in rows]
        return SQLQueryResponse(
            columns=cols,
            rows=serialized_rows,
            duration_ms=duration_ms,
        )
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Security guard: {perm_err}",
        ) from perm_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"DuckDB SQL error: {exc}",
        ) from exc


@app.post(
    "/api/v1/embed",
    response_model=EmbedResponse,
    status_code=status.HTTP_200_OK,
    tags=["Embedding"],
)
def embed_text_endpoint(
    request: EmbedRequest,
    settings: SettingsDep,
    registry: RegistryDep,
) -> EmbedResponse:
    """Generate dense vector embedding for single text string."""
    target_domain = request.domain or settings.app.default_domain
    embedder = registry.get_embedder(target_domain)
    vec = embedder.embed_text(request.text)
    return EmbedResponse(
        text=request.text,
        dimension=len(vec),
        embedding=vec,
    )


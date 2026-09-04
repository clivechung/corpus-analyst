"""FastAPI Query Engine Service for DuckDB Lakehouse RAG Platform.

Follows TREM-Python principles:
- Testable: Dependency injection of Settings via Depends(get_app_settings) for easy test overrides.
- Readable: Fully type-hinted endpoint signatures with explicit Pydantic request/response models.
- Extensible: Modular router design prepared for Phase 6 DuckDB vector retrieval and Gemini synthesis.
- Maintainable: Standard logging, healthcheck probes, and structured error responses.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, status

from src.common.config import Settings, get_settings
from src.common.models import QueryRequest, QueryResponse, RetrievedContextChunk

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Corpus Analyst Query Engine",
    version="0.1.0",
    description="Stateless DuckDB vector lakehouse retrieval and LLM synthesis service.",
)


def get_app_settings() -> Settings:
    """Dependency provider for application settings (TREM: Testable)."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["System"])
def liveness_probe() -> dict[str, str]:
    """Kubernetes and Docker Compose liveness probe endpoint."""
    return {"status": "ok", "service": "query-engine"}


@app.get("/api/v1/health", status_code=status.HTTP_200_OK, tags=["System"])
def detailed_health(settings: SettingsDep) -> dict[str, str]:
    """Service health inspection endpoint with active configuration summary."""
    return {
        "status": "ok",
        "service": "query-engine",
        "version": "0.1.0",
        "environment": settings.app.env,
        "default_domain": settings.app.default_domain,
    }


@app.post(
    "/api/v1/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Query"],
)
def execute_query(
    request: QueryRequest,
    settings: SettingsDep,
) -> QueryResponse:
    """Execute vector retrieval and LLM synthesis over DuckDB lakehouse."""
    logger.info(
        "Received query request: domain=%s question='%s'",
        request.domain or settings.app.default_domain,
        request.question,
    )

    # Phase 2 stub implementation returning typed contract; wired to DuckDB in Phase 6
    return QueryResponse(
        question=request.question,
        answer="Query Engine online. Phase 2 initialization complete; retrieval pipeline activates in Phase 6.",
        domain=request.domain or settings.app.default_domain,
        retrieved_chunks=[],
        citations=[],
        latency_ms=0.0,
        model_used="initialization-stub",
    )


@app.post(
    "/api/v1/search",
    response_model=list[RetrievedContextChunk],
    status_code=status.HTTP_200_OK,
    tags=["Query"],
)
def search_chunks(
    request: QueryRequest,
    settings: SettingsDep,
) -> list[RetrievedContextChunk]:
    """Vector similarity and metadata SQL search returning candidate chunks without synthesis."""
    logger.info(
        "Received search candidate request: domain=%s top_k=%d",
        request.domain or settings.app.default_domain,
        request.top_k,
    )
    return []


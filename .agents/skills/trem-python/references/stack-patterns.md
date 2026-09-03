# Python Preferred Stack Architecture & Patterns

This reference provides implementation patterns for the standard Python stack: `uv`, `typer`, `logging`, `fastapi`, `pydantic`, `alembic` / `sqlalchemy`, and `fastmcp`.

---

## 1. 📦 Package Management: `uv`

Use `uv` for lightning-fast, reproducible dependency management and execution.

### Structure (`pyproject.toml`)
```toml
[project]
name = "my-service"
version = "0.1.0"
description = "TREM-compliant Python service"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.28.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "typer>=0.12.0",
    "sqlalchemy[asyncio]>=2.0.28",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "fastmcp>=0.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.1.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "ruff>=0.3.0",
    "mypy>=1.9.0",
]

[project.scripts]
my-cli = "my_service.cli:app"
```

### Essential `uv` Commands
- Add dependency: `uv add fastapi`
- Add dev dependency: `uv add --dev pytest`
- Run scripts in venv: `uv run pytest` or `uv run python -m my_service.cli`
- Lock dependencies: `uv lock`
- Sync environment: `uv sync`

---

## 2. ⚙️ Configuration: `pydantic-settings`

Centralize all configuration using strongly typed, validated settings with environment variable fallbacks.

```python
from functools import lru_cache
from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MyApp API"
    environment: str = Field(default="development", pattern="^(development|staging|production)$")
    log_level: str = "INFO"
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/myapp"
    )
    api_key_secret: str = Field(default="dev-secret-key", min_length=8)

@lru_cache
def get_settings() -> AppSettings:
    """Cached singleton provider for application settings."""
    return AppSettings()
```

---

## 3. 🪵 Logging: Standard `logging`

Use module-level loggers and avoid modifying root loggers in library code.

```python
import logging
import sys

def setup_logging(log_level: str = "INFO") -> None:
    """Initialize application root handler and formatter."""
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())
    # Avoid duplicate handlers during testing or reload
    if not root_logger.handlers:
        root_logger.addHandler(handler)

# In any application module:
logger = logging.getLogger(__name__)

def execute_task(task_id: str) -> None:
    logger.info("Starting execution for task: %s", task_id)
    try:
        ...
    except Exception as exc:
        logger.error("Failed executing task: %s due to: %s", task_id, exc, exc_info=True)
        raise
```

---

## 4. 🌐 REST APIs: `fastapi`

Use Dependency Injection (`Depends`) to maintain testability and clean layer boundaries.

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from typing import Annotated

router = APIRouter(prefix="/v1/skills", tags=["skills"])

class SkillCreate(BaseModel):
    name: str
    description: str

class SkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str

# Route handler using injected service
@router.post("/", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillCreate,
    service: Annotated[SkillService, Depends(get_skill_service)],
) -> SkillResponse:
    try:
        skill = await service.create_skill(name=payload.name, description=payload.description)
        return SkillResponse.model_validate(skill)
    except DuplicateSkillError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err))
```

---

## 5. 💻 CLI Tools: `typer`

Type-annotated CLI commands with clean error exits and mockable runners.

```python
import typer
import logging
from typing import Optional

app = typer.Typer(help="Skill Management CLI", no_args_is_help=True)
logger = logging.getLogger(__name__)

@app.command()
def sync_skills(
    source_dir: str = typer.Option(..., "--source", "-s", help="Path to skill definitions"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without committing"),
) -> None:
    """Synchronize skill definitions from disk to the registry."""
    typer.echo(f"Scanning skills from {source_dir} (dry-run={dry_run})...")
    # Delegate to domain service
    try:
        # service.sync(source_dir, dry_run)
        typer.secho("✅ Sync completed successfully.", fg=typer.colors.GREEN)
    except Exception as exc:
        logger.error("Sync failed: %s", exc)
        typer.secho(f"❌ Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
```

---

## 6. 🗄️ Database & Migrations: `alembic` + `sqlalchemy` (Async)

Manage database lifecycle cleanly with async engine sessions and explicit Alembic migrations.

### Database Session Dependency
```python
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from my_service.config import get_settings

settings = get_settings()
engine = create_async_engine(str(settings.database_url), echo=False, pool_pre_ping=True)
AsyncSessionFactory = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a managed AsyncSession."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Alembic Workflow
- Initialize: `uv run alembic init -t async migrations`
- Generate Migration: `uv run alembic revision --autogenerate -m "create_items_table"`
- Apply Migrations: `uv run alembic upgrade head`

---

## 7. 🤖 MCP Servers: `fastmcp`

Expose AI tools and resources using `FastMCP` with strict Pydantic schemas and decoupled handlers.

```python
from fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP("App Tools")

class SearchItemsInput(BaseModel):
    query: str = Field(description="Search term or capability query")
    limit: int = Field(default=5, ge=1, le=50, description="Max results to return")

@mcp.tool()
async def search_items(query: str, limit: int = 5) -> str:
    """Search registered items by capability or keyword."""
    # Delegate to underlying domain service
    # results = await item_service.search(query=query, limit=limit)
    return f"Found items matching '{query}' (limit {limit})"
```

---

## 8. 🧪 Testing: Modern Async ASGI Testing (`httpx` + `ASGITransport`)

Avoid `starlette.testclient.TestClient` (which emits `StarletteDeprecationWarning` when using `httpx`) and deprecated `httpx.AsyncClient(app=app)`. Use `httpx.ASGITransport` explicitly:

```python
import pytest
import httpx
from my_app.main import app

@pytest.mark.asyncio
async def test_api_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
```

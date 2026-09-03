# Example: FastAPI + SQLAlchemy + Pydantic TREM Refactor

This walkthrough shows an end-to-end transformation of a legacy, tightly-coupled FastAPI endpoint into a fully TREM-compliant Python architecture.

---

## ❌ Before: The Anti-Pattern Code

```python
# app/routes.py (BAD: Violates T, R, E, and M)
import os
from fastapi import FastAPI, Request
from sqlalchemy import create_engine, text

app = FastAPI()
# Hardcoded global connection using os.getenv
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///test.db"))

@app.post("/api/skills")
async def create_skill(request: Request):
    data = await request.json()
    name = data.get("name")
    desc = data.get("description")
    
    if not name:
        return {"error": "Missing name"}, 400
        
    print(f"Creating skill: {name}") # print instead of logging
    
    # Raw SQL execution and lack of transaction safety
    with engine.connect() as conn:
        try:
            conn.execute(text(f"INSERT INTO skills (name, description) VALUES ('{name}', '{desc}')"))
            conn.commit()
        except Exception as e:
            print("DB error", e) # Swallowed error
            return {"error": "db failure"}
            
    return {"status": "ok", "name": name}
```

### Why it Fails TREM:
- **T (Testable)**: Global `engine` cannot be substituted with a mock or test database fixture; `request.json()` bypasses Pydantic schema validation.
- **R (Readable)**: Raw SQL string formatting (SQL injection risk), lack of type annotations, `print()` debugging.
- **E (Extensible)**: Direct database execution mixed with HTTP handler; impossible to switch to an alternative storage engine or add event listeners.
- **M (Maintainable)**: Swallows exceptions; no Alembic schema management; returns generic dictionary without typed schemas.

---

## ✅ After: TREM-Compliant Architecture

### 1. Configuration (`app/config.py`)
```python
from functools import lru_cache
from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/skills"
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 2. Schemas & Models (`app/schemas.py`)
```python
from pydantic import BaseModel, ConfigDict, Field

class SkillCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)

class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
```

### 3. Protocol & Service Layer (`app/services.py`)
```python
import logging
from typing import Protocol
from app.schemas import SkillCreate, SkillRead

logger = logging.getLogger(__name__)

class SkillRepositoryProtocol(Protocol):
    async def create(self, data: SkillCreate) -> SkillRead: ...
    async def exists_by_name(self, name: str) -> bool: ...

class SkillAlreadyExistsError(Exception):
    """Raised when a skill with the same name already exists."""

class SkillService:
    def __init__(self, repository: SkillRepositoryProtocol) -> None:
        self._repo = repository

    async def register_skill(self, data: SkillCreate) -> SkillRead:
        logger.info("Attempting to register skill: %s", data.name)
        if await self._repo.exists_by_name(data.name):
            logger.warning("Skill registration conflict: %s", data.name)
            raise SkillAlreadyExistsError(f"Skill '{data.name}' already exists.")
        
        created = await self._repo.create(data)
        logger.info("Successfully registered skill id=%s", created.id)
        return created
```

### 4. FastAPI Router & DI (`app/routers/skills.py`)
```python
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas import SkillCreate, SkillRead
from app.services import SkillService, SkillAlreadyExistsError
from app.dependencies import get_skill_service

router = APIRouter(prefix="/skills", tags=["skills"])

@router.post(
    "/",
    response_model=SkillRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new skill",
)
async def create_skill(
    payload: SkillCreate,
    service: Annotated[SkillService, Depends(get_skill_service)],
) -> SkillRead:
    try:
        return await service.register_skill(payload)
    except SkillAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
```

### 5. Automated Tests (`tests/test_skills.py`)
```python
import pytest
from unittest.mock import AsyncMock
from app.schemas import SkillCreate, SkillRead
from app.services import SkillService, SkillAlreadyExistsError

@pytest.mark.asyncio
async def test_register_skill_success():
    # Arrange
    mock_repo = AsyncMock()
    mock_repo.exists_by_name.return_value = False
    mock_repo.create.return_value = SkillRead(id=1, name="Python", description="Programming")
    service = SkillService(repository=mock_repo)

    # Act
    result = await service.register_skill(SkillCreate(name="Python", description="Programming"))

    # Assert
    assert result.id == 1
    assert result.name == "Python"
    mock_repo.create.assert_awaited_once()

@pytest.mark.asyncio
async def test_register_skill_duplicate_raises():
    # Arrange
    mock_repo = AsyncMock()
    mock_repo.exists_by_name.return_value = True
    service = SkillService(repository=mock_repo)

    # Act & Assert
    with pytest.raises(SkillAlreadyExistsError):
        await service.register_skill(SkillCreate(name="Python", description="Programming"))
```

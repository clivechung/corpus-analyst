# Python TREM Principles In-Depth

This document details how the four pillars of TREM (Testable, Readable, Extensible, Maintainable) are applied specifically within the modern Python ecosystem.

---

## 1. 🧪 Testable (T)

Testability ensures that any module, service, endpoint, or CLI command can be verified in isolation with fast, deterministic unit tests.

### Core Tenets in Python
- **Dependency Injection (DI)**: In FastAPI, use `Depends()` providers. In domain services and CLI tools, use constructor injection (`__init__(self, repo: RepoProtocol)`).
- **Avoid Global State & Side-Effects on Import**: Never execute network requests, database connections, or file I/O at module top-level.
- **Fixture-First Testing (`pytest`)**: Leverage `pytest` fixtures for database transactions, mock clients, and configuration overrides.
- **Modern Async ASGI Test Isolation**: Use `pytest-asyncio` with `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`. Avoid legacy `httpx.AsyncClient(app=app)` or `starlette.testclient.TestClient` which trigger deprecation warnings.
- **CLI Testability (`typer.testing.CliRunner`)**: Keep command logic decoupled from presentation so tests can check exit codes, stdout, and error paths without spawning sub-processes.

```python
# GOOD: Fully testable service with injected protocol dependency
from typing import Protocol

class NotificationSender(Protocol):
    async def send(self, recipient: str, message: str) -> bool: ...

class UserService:
    def __init__(self, notifier: NotificationSender) -> None:
        self._notifier = notifier

    async def register_user(self, email: str) -> None:
        # Business logic
        await self._notifier.send(recipient=email, message="Welcome!")
```

---

## 2. 📖 Readable (R)

Readability minimizes cognitive overhead, allowing any engineer or AI agent to understand code behavior immediately.

### Core Tenets in Python
- **Universal Type Hints (PEP 484, PEP 585, PEP 604)**: Use Python 3.10+ union syntax (`int | None`), generic collections (`list[str]`, `dict[str, Any]`), and explicit return types (`-> None`, `-> Result`).
- **Standard Library Logging (`logging`)**: Module-level logger `logger = logging.getLogger(__name__)`. Use proper log levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`) and structured parameters (`logger.info("Processed order", extra={"order_id": order.id})`). Never use `print()`.
- **Guard Clauses & Flat Code**: Exit early on invalid conditions, reducing nested `if/else` blocks to at most 1-2 levels.
- **Pydantic for Data Boundaries**: Use Pydantic models for request bodies, responses, and external payloads to make data shapes self-documenting.

```python
# GOOD: Readable with guard clauses, strict type hints, and standard logging
import logging

logger = logging.getLogger(__name__)

def calculate_discount(price: float, rate: float | None) -> float:
    """Calculate discounted price with rate validation."""
    if price <= 0:
        logger.warning("Attempted discount calculation on non-positive price: %s", price)
        return 0.0

    if rate is None or rate <= 0:
        return price

    discount = price * min(rate, 1.0)
    logger.debug("Applied discount: %s (final: %s)", discount, price - discount)
    return price - discount
```

---

## 3. 🧩 Extensible (E)

Extensibility ensures that new functionality, integrations, or storage backends can be added without modifying existing, tested code (Open/Closed Principle).

### Core Tenets in Python
- **Protocols over ABCs (`typing.Protocol`)**: Use structural subtyping (duck typing with static checking) so new adapters implement contracts without explicit inheritance coupling.
- **Strategy & Plugin Pattern**: Use dictionary registries or dynamic dispatch for algorithms or external providers (e.g. payment processors, LLM model providers, file storage).
- **FastMCP Tool Modularization**: Register new AI tools via decorators without mutating core server logic.

```python
# GOOD: Extensible Strategy Pattern with Protocol
from typing import Protocol, Type

class PaymentProvider(Protocol):
    async def process_payment(self, amount_cents: int) -> str: ...

class PaymentRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Type[PaymentProvider]] = {}

    def register(self, name: str, provider_cls: Type[PaymentProvider]) -> None:
        self._providers[name] = provider_cls

    def get(self, name: str) -> PaymentProvider:
        if name not in self._providers:
            raise ValueError(f"Unknown payment provider: {name}")
        return self._providers[name]()
```

---

## 4. 🛠️ Maintainable (M)

Maintainability ensures code is resilient, easy to debug, safe to modify, and has a minimal blast radius during changes.

### Core Tenets in Python
- **Strict Layer Separation**:
  - `routers/` or `cli/`: Input validation and HTTP/CLI status codes.
  - `services/`: Core business logic, domain rules, and workflows.
  - `repositories/` or `models/`: Database access (SQLAlchemy AsyncSession) and schema definitions.
- **Database Migrations (`alembic`)**: Every database change must have a deterministic migration script. Never run auto-DDL in production applications.
- **Explicit Domain Exceptions**: Define custom exception hierarchies inheriting from a base domain exception (`AppError`). Translate domain errors to HTTP errors (`HTTPException`) only at the API layer.
- **Package Management with `uv`**: Always pin dependencies with `pyproject.toml` and lockfiles for deterministic reproducible builds.

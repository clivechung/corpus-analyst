# Python Anti-Patterns & Code Smells

This document catalogs common anti-patterns in Python applications and how to resolve them according to the TREM framework.

---

## 1. 🧪 Testability Anti-Patterns

### Anti-Pattern 1.1: Direct Global Instantiation
- ❌ **Smell**: Creating database engines, API clients, or settings instances inside modules or route functions directly.
- 💡 **Consequence**: Unit tests cannot mock dependencies without monkey-patching globals; concurrent tests interfere with each other.
- ✅ **TREM Fix**: Pass instances via `__init__` constructor injection or FastAPI `Depends()`.

```python
# BAD
db = create_async_engine("postgresql+asyncpg://...")
@app.get("/users")
async def get_users():
    async with db.connect() as conn: ...

# GOOD
@app.get("/users")
async def get_users(session: Annotated[AsyncSession, Depends(get_db_session)]):
    ...
```

### Anti-Pattern 1.2: Hardcoded Time and Randomness
- ❌ **Smell**: Calling `datetime.now()` or `random.choice()` directly inside core business rules.
- 💡 **Consequence**: Non-deterministic tests; impossible to test time-based expiry or edge cases.
- ✅ **TREM Fix**: Inject a clock/provider protocol or pass timestamp as an argument.

### Anti-Pattern 1.3: Deprecated Synchronous or Untransported ASGI Test Clients
- ❌ **Smell**: Using `starlette.testclient.TestClient` with modern `httpx`, or passing `httpx.AsyncClient(app=app)`.
- 💡 **Consequence**: Triggers runtime `StarletteDeprecationWarning` or fails with modern `httpx` versions (0.27+).
- ✅ **TREM Fix**: Use `pytest-asyncio` and `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`.

---

## 2. 📖 Readability Anti-Patterns

### Anti-Pattern 2.1: Missing or Vague Type Annotations
- ❌ **Smell**: Using `Any`, unparameterized `list`, `dict`, or omitting return types entirely.
- 💡 **Consequence**: IDE and static analysis tools (`mypy`/`pyright`) cannot detect type mismatches; reading code requires inspecting runtime values.
- ✅ **TREM Fix**: Use PEP 585/604 annotations: `list[str]`, `dict[str, int]`, `str | None`.

### Anti-Pattern 2.2: Using `print()` Instead of `logging`
- ❌ **Smell**: Sprinkling `print(f"Debug: {var}")` throughout the codebase.
- 💡 **Consequence**: No log levels, timestamps, module context, or ability to filter output in production.
- ✅ **TREM Fix**: Use `logger = logging.getLogger(__name__)` and structured logging statements.

### Anti-Pattern 2.3: Deep Nesting & Arrow Code
- ❌ **Smell**: Multiple levels of nested `if/elif/else/try` blocks.
- 💡 **Consequence**: High cyclomatic complexity and difficult cognitive tracking.
- ✅ **TREM Fix**: Use guard clauses with early returns and extract subroutines.

---

## 3. 🧩 Extensibility Anti-Patterns

### Anti-Pattern 3.1: Mega `if/elif` Type Dispatching
- ❌ **Smell**: Large conditionals checking message types or payment providers.
- 💡 **Consequence**: Violates Open/Closed Principle; adding a new type requires modifying and risking existing logic.
- ✅ **TREM Fix**: Use `typing.Protocol` with a registry or Strategy pattern.

```python
# BAD
if provider == "stripe":
    ...
elif provider == "paypal":
    ...
elif provider == "adyen":
    ...

# GOOD: Dynamic dispatch using Registry
provider = payment_registry.get(provider_name)
await provider.charge(amount)
```

---

## 4. 🛠️ Maintainability Anti-Patterns

### Anti-Pattern 4.1: Bare `except:` or Swallowed Exceptions
- ❌ **Smell**:
  ```python
  try:
      do_something()
  except Exception:
      pass  # or print("error")
  ```
- 💡 **Consequence**: Silently masks critical bugs, syntax errors, and database connection timeouts.
- ✅ **TREM Fix**: Catch specific exceptions, log with `logger.error(..., exc_info=True)`, and re-raise or wrap in a domain exception.

### Anti-Pattern 4.2: Leaking Database Models to the API Layer
- ❌ **Smell**: Returning SQLAlchemy ORM models directly in FastAPI responses.
- 💡 **Consequence**: Unintentional serialization of sensitive columns, lazy-loading errors outside async session context, tightly coupling DB schema to public API contracts.
- ✅ **TREM Fix**: Use distinct Pydantic DTOs for request input and response serialization (`response_model=SkillRead`).

### Anti-Pattern 4.3: Direct Database DDL Without Alembic Migrations
- ❌ **Smell**: Calling `Base.metadata.create_all()` in production code.
- 💡 **Consequence**: Schema changes cannot be versioned, rolled back, or audited safely across environments.
- ✅ **TREM Fix**: Use `alembic revision --autogenerate` and `alembic upgrade head`.

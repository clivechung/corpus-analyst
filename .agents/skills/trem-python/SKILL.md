---
name: trem-python
description: >-
  Reviews, audits, refactors, and generates Python code following the TREM principles (Testable, Readable, Extensible, Maintainable)
  using the modern Python ecosystem: uv, Typer, logging, FastAPI, Pydantic, Alembic/SQLAlchemy, and FastMCP.
  Use this skill whenever working on Python code reviews, architecture design, API implementation, CLI development, or refactoring.
category: software
---

# TREM Python Engineering Framework

A tailored Python implementation of the **TREM** engineering framework (Testable, Readable, Extensible, Maintainable) optimized for the modern Python ecosystem.

---

## 🏗️ Standard Python Technology Stack

| Capability | Standard Tool / Library | Key TREM Best Practice |
| :--- | :--- | :--- |
| **Package Manager** | `uv` | Declarative `pyproject.toml`, reproducible `uv.lock`, fast virtual environments with `uv run` and `uv add`. |
| **Configuration** | `pydantic` / `pydantic-settings` | Strongly-typed `BaseSettings`, environment variable loading, immutable configurations, validated input boundaries. |
| **Logging** | Standard library `logging` | Module-level `logger = logging.getLogger(__name__)`, structured log formatters, lazy formatting (`%s`), never `print()`. |
| **CLI Applications** | `typer` | Type-annotated CLI interfaces, dependency-injected helpers, tested with `typer.testing.CliRunner`. |
| **REST APIs** | `fastapi` | Dependency Injection via `Depends()`, Pydantic request/response models, isolated `APIRouter` modules, async I/O. |
| **Database & Migrations** | `alembic` + `sqlalchemy` (Async) | Declarative models, repository/unit-of-work patterns, automated schema migrations with Alembic, injected async sessions. |
| **MCP Servers** | `fastmcp` (or official MCP SDK) | Modular tool/resource definitions, decoupled business logic, strict type annotations, structured error returns. |
| **Testing** | `pytest` + `pytest-asyncio` | Fixtures with explicit scope, `unittest.mock` / `AsyncMock`, `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` for warning-free ASGI testing. |

---

## ⚡ Python TREM Assessment Checklist

| Pillar | Python-Specific Focus | Verification Question |
| :--- | :--- | :--- |
| **T** (Testable) | **FastAPI `Depends`, Constructor Injection, Pytest Fixtures** | Are database sessions, HTTP clients, and clocks injected via arguments/`Depends` rather than instantiated globally or in function bodies? |
| **R** (Readable) | **Type Hints (PEP 484/585), Guard Clauses, Docstrings** | Are all function signatures strictly type-hinted? Is cyclomatic complexity minimized with early returns and descriptive variable names? |
| **E** (Extensible) | **Protocols (`typing.Protocol`), Pydantic Models, Strategies** | Are service interfaces defined with `Protocol` or ABCs allowing pluggable implementations (e.g. storage providers, notification backends)? |
| **M** (Maintainable) | **Layer Separation, Domain Exceptions, Alembic Migrations** | Are routers/CLIs separated from business logic and database access? Are custom exceptions handled uniformly without bare `except:`? |

---

## 🛠️ Workflows

### Workflow 1: Python Code Review & TREM Audit

Use this workflow to review Python code, PRs, or existing services.

1. **Package & Environment Check**:
   - Verify dependencies are managed via `pyproject.toml` (`uv`).
   - Ensure configuration values are modeled using `pydantic-settings` with validation.
2. **Layering & Separation Audit**:
   - **Router / CLI Layer**: Ensure `fastapi.APIRouter` or `typer.Typer` only handles input parsing, response formatting, and delegation.
   - **Domain / Service Layer**: Ensure business logic contains no direct FastAPI request objects, CLI output statements, or raw SQL queries.
   - **Data Access Layer**: Ensure database queries use SQLAlchemy async sessions and schema migrations are tracked via `alembic`.
   - **MCP Layer**: Ensure `FastMCP` tools delegate to domain services rather than embedding business logic.
3. **Pillar Evaluation**:
   - **Testability**: Can service functions and routes be tested using `pytest` without spinning up real external databases or network calls?
   - **Readability**: Are type annotations universal? Is standard `logging` configured properly without bare `print`?
   - **Extensibility**: Are abstract interfaces (`typing.Protocol`) used for polymorphic components?
   - **Maintainability**: Are errors caught as specific exception types with structured logging context?
4. **Generate Structured TREM Report**: Produce output matching the [TREM Review Template](#-standard-trem-review-output-template).

---

### Workflow 2: Python Code Generation & Implementation

Use this workflow when creating new Python modules, CLI tools, REST APIs, or MCP servers.

1. **Step 1: Configuration & Models (`pydantic`)**:
   - Create settings using `pydantic_settings.BaseSettings`.
   - Define domain and DTO models using `pydantic.BaseModel` with strict typing.
2. **Step 2: Define Service Contracts & Domain Logic**:
   - Use `typing.Protocol` for dependencies (repositories, external APIs, mailers).
   - Implement business logic classes with constructor-injected dependencies.
   - Use `logging.getLogger(__name__)` for traceable operational logs.
3. **Step 3: Implement Data Access (`alembic` & `sqlalchemy`)**:
   - Define SQLAlchemy declarative models.
   - Implement repository adapters satisfying the domain `Protocol`.
   - Write clean Alembic migration scripts for schema changes.
4. **Step 4: Implement Entry Points (`fastapi`, `typer`, `fastmcp`)**:
   - **FastAPI**: Wire dependencies with `Depends()`, return Pydantic response models, handle errors via exception handlers.
   - **Typer**: Define CLI commands with type hints, output using `typer.echo` / `rich`, and isolate command actions.
   - **FastMCP**: Expose server tools using `@mcp.tool()` decorating domain service invocations.
5. **Step 5: Write Automated Tests (`pytest`)**:
   - Write unit tests mocking dependencies via `pytest.fixture` or `unittest.mock.AsyncMock`.
   - Write integration tests with `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")` (FastAPI / Starlette) or `typer.testing.CliRunner` (Typer).

---

### Workflow 3: Python TREM Refactoring

Use this workflow to refactor legacy, tightly-coupled, or unmaintainable Python code.

1. **Decouple Database & Globals**:
   - Eliminate global DB engines or session variables. Inject `AsyncSession` into repositories.
   - Create Alembic migrations for unversioned database structures.
2. **Replace Direct Config / `os.environ`**:
   - Replace scattered `os.getenv()` calls with a centralized `pydantic_settings.BaseSettings` class.
3. **Invert Dependencies in FastAPI & Typer**:
   - Replace inline service instantiation with FastAPI `Depends(get_service)`.
   - Decouple Typer commands into CLI parsing + core service calls.
4. **Clean up Logging & Error Handling**:
   - Replace all `print()` with `logger.info()`, `logger.warning()`, `logger.error()`.
   - Convert bare `except Exception:` into specific domain error handling and HTTP/CLI translation.

---

## 📋 Standard TREM Review Output Template

````markdown
# 🛡️ TREM Python Code Review Report

## Executive Summary
[Summary of the Python codebase/module, architectural strengths, and critical areas for improvement.]

## 📊 TREM Scorecard

| Pillar | Status | Key Observations (Python Stack) |
| :--- | :---: | :--- |
| **Testable** | 🟢/🟡/🔴 | [e.g., FastAPI DI coverage, pytest fixture readiness, mockability] |
| **Readable** | 🟢/🟡/🔴 | [e.g., Type hints, standard logging, guard clauses, docstrings] |
| **Extensible** | 🟢/🟡/🔴 | [e.g., Protocol definitions, Pydantic polymorphism, Strategy pattern] |
| **Maintainable** | 🟢/🟡/🔴 | [e.g., Alembic migrations, error handling, layer separation] |

---

## 🔍 Detailed Findings & Recommendations

### 1. Testability (T)
- ⚠️ **[Issue]** (Line XX-YY): [e.g., Database engine initialized inside endpoint instead of injected with `Depends`]
  - **Remediation**: [e.g., Extract to `get_db_session` dependency provider]

### 2. Readability (R)
- 💡 **[Issue]** (Line XX-YY): [e.g., `print()` statements used instead of `logging.getLogger(__name__)`]
  - **Remediation**: [e.g., Replace with structured `logger.info()` with contextual parameters]

### 3. Extensibility (E)
- ⚠️ **[Issue]** (Line XX-YY): [e.g., Hardcoded third-party API integration with no Protocol abstraction]
  - **Remediation**: [e.g., Define `class ClientProtocol(typing.Protocol)` and inject adapter]

### 4. Maintainability (M)
- 🚨 **[Issue]** (Line XX-YY): [e.g., Schema mutation without Alembic migration; missing Pydantic validation]
  - **Remediation**: [e.g., Add Alembic migration script and schema model]

---

## 🚀 Refactored Implementation

```python
# Fully compliant, modern Python TREM implementation
```
````

---

## 📚 Deep Dive References & Examples

- [Python TREM Principles](references/python-trem-principles.md) — Comprehensive guide on applying T, R, E, and M in Python.
- [Stack Architecture & Recipes](references/stack-patterns.md) — Patterns and best practices for `uv`, `typer`, `fastapi`, `pydantic`, `logging`, `alembic`, and `fastmcp`.
- [Python Anti-Patterns](references/anti-patterns-python.md) — Common Python code smells and their TREM solutions.
- [FastAPI + SQLAlchemy Refactor Walkthrough](examples/fastapi-trem-refactor.md) — Step-by-step refactoring example.
- [Typer CLI + FastMCP Server Example](examples/typer-fastmcp-example.md) — Building testable CLIs and MCP servers with shared domain logic.

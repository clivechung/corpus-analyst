# Example: Typer CLI + FastMCP Server with Shared Domain

This example demonstrates how to build both a CLI tool (`typer`) and an AI Model Context Protocol server (`fastmcp`) sharing the same testable domain services.

---

## 📁 Architecture Overview

```text
src/task_hub/
├── config.py         # Pydantic Settings
├── domain/
│   ├── models.py     # Pydantic domain models
│   └── service.py    # Core business logic (Protocol-driven)
├── cli.py            # Typer CLI entrypoint
├── mcp_server.py     # FastMCP server entrypoint
└── logging_config.py # Standard logging setup
```

---

## 1. Shared Domain Service (`src/task_hub/domain/service.py`)

```python
import logging
from typing import Protocol
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class TaskItem(BaseModel):
    name: str
    priority: str
    description: str

class TaskStorageProtocol(Protocol):
    async def list_all(self) -> list[TaskItem]: ...
    async def add(self, item: TaskItem) -> None: ...

class TaskManagerService:
    def __init__(self, storage: TaskStorageProtocol) -> None:
        self._storage = storage

    async def list_tasks(self, priority: str | None = None) -> list[TaskItem]:
        logger.info("Listing tasks (filter priority=%s)", priority)
        items = await self._storage.list_all()
        if priority:
            items = [i for i in items if i.priority.lower() == priority.lower()]
        return items

    async def register(self, name: str, priority: str, description: str) -> TaskItem:
        item = TaskItem(name=name, priority=priority, description=description)
        await self._storage.add(item)
        logger.info("Registered task '%s' with priority '%s'", name, priority)
        return item
```

---

## 2. Typer CLI Interface (`src/task_hub/cli.py`)

```python
import asyncio
import typer
from rich.console import Console
from rich.table import Table
from task_hub.domain.service import TaskManagerService
from task_hub.adapters.filesystem import FileSystemStorage

app = typer.Typer(name="task-hub", help="Task Management CLI", no_args_is_help=True)
console = Console()

def get_service() -> TaskManagerService:
    return TaskManagerService(storage=FileSystemStorage())

@app.command("list")
def list_tasks(
    priority: str = typer.Option(None, "--priority", "-p", help="Filter by priority"),
) -> None:
    """List all available tasks."""
    service = get_service()
    tasks = asyncio.run(service.list_tasks(priority=priority))

    if not tasks:
        console.print("[yellow]No tasks found.[/yellow]")
        return

    table = Table(title="Available Tasks")
    table.add_column("Name", style="cyan bold")
    table.add_column("Priority", style="green")
    table.add_column("Description")

    for t in tasks:
        table.add_row(t.name, t.priority, t.description)

    console.print(table)

@app.command("add")
def add_task(
    name: str = typer.Argument(..., help="Name of the task"),
    priority: str = typer.Option("medium", "--priority", "-p", help="Task priority"),
    desc: str = typer.Option("", "--desc", "-d", help="Task description"),
) -> None:
    """Add a new task to the registry."""
    service = get_service()
    asyncio.run(service.register(name=name, priority=priority, description=desc))
    console.print(f"[bold green]✓[/bold green] Added task: [cyan]{name}[/cyan]")

if __name__ == "__main__":
    app()
```

---

## 3. FastMCP Server Interface (`src/task_hub/mcp_server.py`)

```python
from fastmcp import FastMCP
from task_hub.domain.service import TaskManagerService
from task_hub.adapters.filesystem import FileSystemStorage

mcp = FastMCP("TaskHub MCP Server")
service = TaskManagerService(storage=FileSystemStorage())

@mcp.tool()
async def search_available_tasks(priority: str | None = None) -> list[dict]:
    """Retrieve tasks registered in TaskHub, optionally filtered by priority."""
    tasks = await service.list_tasks(priority=priority)
    return [task.model_dump() for task in tasks]

@mcp.tool()
async def register_new_task(name: str, priority: str, description: str) -> str:
    """Register a new task into the repository."""
    created = await service.register(name=name, priority=priority, description=description)
    return f"Successfully registered {created.name} with priority {created.priority}."

if __name__ == "__main__":
    mcp.run()
```

---

## 4. CLI Unit Testing with `CliRunner` (`tests/test_cli.py`)

```python
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock
from task_hub.cli import app
from task_hub.domain.service import TaskItem

runner = CliRunner()

def test_cli_list_command():
    with patch("task_hub.cli.get_service") as mock_get_svc:
        mock_svc = AsyncMock()
        mock_svc.list_tasks.return_value = [
            TaskItem(name="database-migration", priority="high", description="Run alembic migrations")
        ]
        mock_get_svc.return_value = mock_svc

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "database-migration" in result.stdout
```

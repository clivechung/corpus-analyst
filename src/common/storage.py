"""Pluggable Lakehouse Storage Backend Architecture.

Follows TREM-Python principles:
- Testable: StorageBackendProtocol allows trivial in-memory and filesystem mocking.
- Readable: Explicit method contracts with type hints and descriptive docstrings.
- Extensible: Strategy pattern enabling seamless switching between LocalFS and Cloud Azure Blob.
- Maintainable: Central factory with isolated provider implementations and graceful fallbacks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.common.config import Settings, get_settings

logger = logging.getLogger(__name__)


@runtime_checkable
class StorageBackendProtocol(Protocol):
    """Protocol contract for lakehouse Parquet and document storage backends."""

    def initialize(self) -> None:
        """Initialize the storage target (e.g. create local directory or remote container)."""
        ...

    def is_healthy(self) -> bool:
        """Verify storage accessibility and read/write health."""
        ...

    def list_files(self, prefix: str = "") -> list[str]:
        """List object keys or file paths relative to storage root matching prefix."""
        ...

    def read_bytes(self, path: str) -> bytes:
        """Read content bytes for a given relative path/key."""
        ...

    def write_bytes(self, path: str, data: bytes) -> str:
        """Persist content bytes to path/key and return absolute or canonical URI."""
        ...


class LocalStorageBackend:
    """Local filesystem storage backend for zero-overhead lakehouse operations."""

    def __init__(self, base_path: str = "/data/lake") -> None:
        self.base_path = Path(base_path)

    def initialize(self) -> None:
        """Ensure base directory exists on disk."""
        logger.info("Initializing LocalFS lakehouse storage at: %s", self.base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def is_healthy(self) -> bool:
        """Verify local directory exists and is writable."""
        if not self.base_path.exists():
            return False
        return os.access(self.base_path, os.R_OK | os.W_OK)

    def list_files(self, prefix: str = "") -> list[str]:
        """List relative file paths matching prefix under base_path."""
        if not self.base_path.exists():
            return []

        search_root = self.base_path / prefix if prefix else self.base_path
        if not search_root.exists():
            return []

        results: list[str] = []
        for path in search_root.rglob("*"):
            if path.is_file():
                results.append(str(path.relative_to(self.base_path)))
        return sorted(results)

    def read_bytes(self, path: str) -> bytes:
        """Read bytes from target local file."""
        target = self.base_path / path
        if not target.exists():
            raise FileNotFoundError(f"File not found in local lakehouse: {target}")
        return target.read_bytes()

    def write_bytes(self, path: str, data: bytes) -> str:
        """Write bytes to local path, automatically creating parent directories."""
        target = self.base_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        logger.debug("Wrote %d bytes to localfs: %s", len(data), target)
        return str(target)


class AzureBlobStorageBackend:
    """Cloud Azure Blob Storage backend adapter (pluggable extension for production)."""

    def __init__(
        self,
        container_name: str = "corpus-lake",
        connection_string: str = "",
    ) -> None:
        self.container_name = container_name
        self.connection_string = connection_string
        self._client: Any = None

    def _get_client(self) -> Any:
        if not self.connection_string:
            return None
        if self._client is None:
            try:
                from azure.storage.blob import BlobServiceClient

                self._client = BlobServiceClient.from_connection_string(self.connection_string)
            except ImportError:
                logger.warning("azure-storage-blob not installed; AzureBlobStorageBackend inactive.")
            except Exception as exc:
                logger.error("Failed to initialize Azure Blob client: %s", exc)
        return self._client

    def initialize(self) -> None:
        """Ensure cloud Azure Blob container exists."""
        client = self._get_client()
        if not client:
            logger.info("AzureBlobStorageBackend: No active connection string configured.")
            return

        try:
            from azure.core.exceptions import ResourceExistsError

            client.create_container(self.container_name)
            logger.info("Created cloud Azure container: %s", self.container_name)
        except Exception:
            logger.debug("Container %s already exists or connection deferred.", self.container_name)

    def is_healthy(self) -> bool:
        """Verify cloud Azure Blob connection status."""
        client = self._get_client()
        if not client:
            return False
        try:
            container_client = client.get_container_client(self.container_name)
            return container_client.exists()
        except Exception as exc:
            logger.debug("Azure blob health probe failed: %s", exc)
            return False

    def list_files(self, prefix: str = "") -> list[str]:
        """List blobs matching prefix in cloud container."""
        client = self._get_client()
        if not client:
            return []
        try:
            container_client = client.get_container_client(self.container_name)
            return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
        except Exception as exc:
            logger.error("Failed to list blobs: %s", exc)
            return []

    def read_bytes(self, path: str) -> bytes:
        """Download blob content from cloud container."""
        client = self._get_client()
        if not client:
            raise ConnectionError("Azure Blob client not configured.")
        blob_client = client.get_blob_client(container=self.container_name, blob=path)
        return blob_client.download_blob().readall()

    def write_bytes(self, path: str, data: bytes) -> str:
        """Upload blob content to cloud container."""
        client = self._get_client()
        if not client:
            raise ConnectionError("Azure Blob client not configured.")
        blob_client = client.get_blob_client(container=self.container_name, blob=path)
        blob_client.upload_blob(data, overwrite=True)
        return f"azure://{self.container_name}/{path}"


def get_storage_backend(settings: Settings | None = None) -> StorageBackendProtocol:
    """Factory creating configured storage backend instance (TREM: Extensible)."""
    cfg = settings or get_settings()
    provider = cfg.storage.provider.lower().strip()

    if provider == "localfs":
        return LocalStorageBackend(base_path=cfg.storage.local_path)
    elif provider in ("azure_blob", "azure"):
        return AzureBlobStorageBackend(
            container_name=cfg.storage.azure_container_name,
            connection_string=cfg.storage.azure_storage_connection_string,
        )
    else:
        raise ValueError(
            f"Unsupported storage provider '{provider}'. Valid options: 'localfs', 'azure_blob'."
        )


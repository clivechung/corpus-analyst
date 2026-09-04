"""Unit tests for pluggable lakehouse storage backend seam (SEAM-STORAGE).

Follows TREM principles:
- Testable: In-memory/tempdir testing without requiring cloud resources or live emulators.
- Readable: Direct assertions on read, write, list, and healthcheck operations.
- Extensible: Protocol verification ensuring LocalFS and future Azure Blob implementations match.
- Maintainable: Verification of clean directory creation and error handling.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.common.config import Settings
from src.common.storage import (
    AzureBlobStorageBackend,
    LocalStorageBackend,
    StorageBackendProtocol,
    get_storage_backend,
)


class TestStorageSeam(unittest.TestCase):
    """Test suite for pluggable storage architecture."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lake_dir = Path(self.temp_dir.name) / "lake"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_local_storage_satisfies_protocol(self) -> None:
        """Verify LocalStorageBackend adheres to StorageBackendProtocol (TREM: Extensible)."""
        backend = LocalStorageBackend(base_path=str(self.lake_dir))
        self.assertIsInstance(backend, StorageBackendProtocol)

    def test_local_storage_initialize_creates_directory(self) -> None:
        """Verify initialize creates base lakehouse directory."""
        backend = LocalStorageBackend(base_path=str(self.lake_dir))
        self.assertFalse(self.lake_dir.exists())

        backend.initialize()
        self.assertTrue(self.lake_dir.exists())
        self.assertTrue(backend.is_healthy())

    def test_local_storage_write_read_and_list(self) -> None:
        """Verify reading, writing, and listing parquet/files in localfs."""
        backend = LocalStorageBackend(base_path=str(self.lake_dir))
        backend.initialize()

        test_data = b"PARQUET1_MOCK_DATA_12345"
        rel_path = "domain=finance/year=2024/month=02/batch_01.parquet"

        # Write bytes
        written_path = backend.write_bytes(rel_path, test_data)
        self.assertTrue(Path(written_path).exists())

        # Read bytes
        read_data = backend.read_bytes(rel_path)
        self.assertEqual(read_data, test_data)

        # List files
        files = backend.list_files(prefix="domain=finance")
        self.assertEqual(len(files), 1)
        self.assertIn("batch_01.parquet", files[0])

    def test_azure_blob_storage_satisfies_protocol(self) -> None:
        """Verify AzureBlobStorageBackend adheres to StorageBackendProtocol (Future Extension)."""
        backend = AzureBlobStorageBackend(
            container_name="corpus-lake",
            connection_string="",
        )
        self.assertIsInstance(backend, StorageBackendProtocol)
        # Without connection string, reports unhealthy gracefully
        self.assertFalse(backend.is_healthy())

    def test_get_storage_backend_factory(self) -> None:
        """Verify get_storage_backend returns correct backend instance based on configuration."""
        # Localfs backend
        local_settings = Settings()
        local_settings.storage.provider = "localfs"
        local_settings.storage.local_path = str(self.lake_dir)

        backend = get_storage_backend(local_settings)
        self.assertIsInstance(backend, LocalStorageBackend)

        # Azure blob backend (future extension)
        azure_settings = Settings()
        azure_settings.storage.provider = "azure_blob"
        azure_settings.storage.azure_container_name = "test-lake"

        backend_azure = get_storage_backend(azure_settings)
        self.assertIsInstance(backend_azure, AzureBlobStorageBackend)


if __name__ == "__main__":
    unittest.main()


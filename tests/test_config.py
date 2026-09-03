"""Unit tests for configuration loading and validation seam (TREM: Testable, Maintainable)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.common.config import (
    EmbeddingModelProfile,
    ModelRegistryConfig,
    Settings,
    get_settings,
    load_model_profiles,
)


class TestConfigSeam(unittest.TestCase):
    """Test suite for the public configuration seam."""

    def test_default_settings(self) -> None:
        """Verify fallback defaults when no file is specified."""
        settings = Settings()
        self.assertEqual(settings.app.env, "development")
        self.assertEqual(settings.app.default_domain, "finance")
        self.assertEqual(settings.chunking.max_chunk_tokens, 512)
        self.assertEqual(settings.chunking.chunk_overlap_tokens, 64)
        self.assertEqual(settings.query.port, 8000)
        self.assertEqual(settings.llm.provider, "gemini")

    def test_load_from_yaml_file(self) -> None:
        """Verify loading and overriding configuration from a valid YAML file."""
        yaml_content = """
app:
  env: production
  default_domain: literature
  log_level: DEBUG

paths:
  lake_path: /custom/lake
  incoming_path: /custom/incoming

chunking:
  max_chunk_tokens: 1024
  chunk_overlap_tokens: 128

query:
  port: 9000
  default_top_k: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            settings = Settings.load(config_path=temp_path)
            self.assertEqual(settings.app.env, "production")
            self.assertEqual(settings.app.default_domain, "literature")
            self.assertEqual(settings.app.log_level, "DEBUG")
            self.assertEqual(settings.paths.lake_path, "/custom/lake")
            self.assertEqual(settings.chunking.max_chunk_tokens, 1024)
            self.assertEqual(settings.chunking.chunk_overlap_tokens, 128)
            self.assertEqual(settings.query.port, 9000)
            self.assertEqual(settings.query.default_top_k, 10)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_env_var_overrides(self) -> None:
        """Verify environment variables take precedence over config files."""
        yaml_content = """
app:
  env: staging
  default_domain: finance
chunking:
  max_chunk_tokens: 256
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            env_vars = {
                "APP_ENV": "production",
                "DEFAULT_DOMAIN": "general",
                "MAX_CHUNK_TOKENS": "768",
                "GEMINI_API_KEY": "test-key-12345",
            }
            with mock.patch.dict(os.environ, env_vars, clear=False):
                settings = Settings.load(config_path=temp_path)
                self.assertEqual(settings.app.env, "production")
                self.assertEqual(settings.app.default_domain, "general")
                self.assertEqual(settings.chunking.max_chunk_tokens, 768)
                self.assertEqual(settings.llm.gemini_api_key, "test-key-12345")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_model_profiles_from_json(self) -> None:
        """Verify parsing model registry profiles from JSON specification."""
        profiles_json = {
            "version": "1.0.0",
            "default_profile": "finance",
            "profiles": {
                "finance": {
                    "name": "finance",
                    "model_name": "BAAI/bge-small-en-v1.5",
                    "dimension": 384,
                    "max_sequence_length": 512,
                    "batch_size": 32,
                    "normalize_embeddings": True,
                    "description": "Finance model",
                }
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(profiles_json, f)
            temp_path = f.name

        try:
            registry = load_model_profiles(path=temp_path)
            self.assertIsInstance(registry, ModelRegistryConfig)
            self.assertIn("finance", registry.profiles)
            profile = registry.profiles["finance"]
            self.assertEqual(profile.dimension, 384)
            self.assertEqual(profile.model_name, "BAAI/bge-small-en-v1.5")
            self.assertTrue(profile.normalize_embeddings)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_model_profiles_file_not_found(self) -> None:
        """Verify FileNotFoundError is raised cleanly when models config is missing."""
        with self.assertRaises(FileNotFoundError):
            load_model_profiles(path="/non/existent/path/models.json")

    def test_get_settings_singleton_and_custom(self) -> None:
        """Verify get_settings returns a valid Settings instance."""
        settings = get_settings()
        self.assertIsInstance(settings, Settings)


if __name__ == "__main__":
    unittest.main()


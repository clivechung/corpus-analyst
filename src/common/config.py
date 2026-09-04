"""Unified configuration and settings core for corpus-analyst platform.

Follows TREM-Python principles:
- Testable: Fully injectable paths and dictionary overrides.
- Readable: Strictly type-hinted Pydantic schemas with descriptive docstrings.
- Extensible: Sub-models for storage, chunking, embedding, query, and LLM providers.
- Maintainable: Centralized configuration parsing with graceful fallbacks.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Domain & Embedding Registry Models
# -----------------------------------------------------------------------------


class EmbeddingModelProfile(BaseModel):
    """Specification for a domain-specific dense embedding model."""

    name: str = Field(description="Profile identifier, e.g. 'finance', 'literature'")
    model_name: str = Field(description="HuggingFace model hub repository or local weight path")
    dimension: int = Field(gt=0, description="Output embedding dense vector dimension")
    max_sequence_length: int = Field(default=512, gt=0, description="Max token context window")
    batch_size: int = Field(default=32, gt=0, description="Inference batch size")
    normalize_embeddings: bool = Field(default=True, description="Whether to L2-normalize vectors")
    description: str = Field(default="", description="Human-readable profile notes")


class ModelRegistryConfig(BaseModel):
    """Root configuration containing all available domain embedding profiles."""

    version: str = Field(default="1.0.0", description="Configuration schema version")
    default_profile: str = Field(default="finance", description="Default domain profile to use")
    profiles: dict[str, EmbeddingModelProfile] = Field(
        default_factory=dict, description="Dictionary of profile keys to specs"
    )


# -----------------------------------------------------------------------------
# Service & Subsystem Settings
# -----------------------------------------------------------------------------


class AppSettings(BaseModel):
    """Core application environment and logging settings."""

    env: str = Field(default="development", description="Runtime environment (development, staging, production)")
    log_level: str = Field(default="INFO", description="Standard logging level")
    default_domain: str = Field(default="finance", description="Default operational corpus domain")


class PathSettings(BaseModel):
    """Filesystem mount paths for ingestion, processing, and lakehouse storage."""

    lake_path: str = Field(default="/data/lake", description="Hive-partitioned parquet lake directory")
    incoming_path: str = Field(default="/data/incoming", description="Drop-directory for newly received raw files")
    processed_path: str = Field(default="/data/processed", description="Directory for successfully ingested documents")
    failed_path: str = Field(default="/data/failed", description="Dead-letter directory for malformed files")
    model_cache_dir: str = Field(default="/root/.cache/huggingface", description="Shared model cache volume")


class ChunkingSettings(BaseModel):
    """Parameters governing document partitioning and token splitting."""

    max_chunk_tokens: int = Field(default=512, gt=0, description="Strict upper bound token limit per chunk")
    chunk_overlap_tokens: int = Field(default=64, ge=0, description="Sliding window context overlap in tokens")
    max_characters: int = Field(default=2000, gt=0, description="Character threshold for oversized elements")


class StorageSettings(BaseModel):
    """Pluggable lakehouse storage backend configuration."""

    provider: str = Field(default="localfs", description="Storage provider ('localfs' or 'azure_blob')")
    local_path: str = Field(default="/data/lake", description="Base path for localfs lakehouse storage")
    azure_container_name: str = Field(default="corpus-lake", description="Target container for cloud Azure Blob")
    azure_storage_connection_string: str = Field(
        default="", description="Azure blob connection string (for cloud Azure Blob extension)"
    )


class QuerySettings(BaseModel):
    """DuckDB vector search and query engine API configurations."""

    host: str = Field(default="0.0.0.0", description="REST API bind host")
    port: int = Field(default=8000, gt=0, description="REST API port")
    default_top_k: int = Field(default=5, ge=1, le=100, description="Default number of chunks retrieved")
    similarity_threshold: float = Field(default=0.0, ge=-1.0, le=1.0, description="Minimum cosine similarity cutoff")
    duckdb_path: str = Field(default=":memory:", description="In-process DuckDB database path")


class LLMSettings(BaseModel):
    """LLM provider parameters for grounded answer synthesis."""

    provider: str = Field(default="gemini", description="LLM provider: 'gemini' or 'ollama'")
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = Field(default="gemini-2.5-flash", description="Gemini model ID")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Local Ollama instance URL")
    ollama_model: str = Field(default="qwen2.5:7b", description="Local Ollama model ID")


class SECSettings(BaseModel):
    """SEC EDGAR fetcher parameters."""

    user_agent: str = Field(
        default="CorpusAnalystAdmin admin@corpus-analyst.local",
        description="SEC-compliant User-Agent header (Sample Company Name AdminContact@domain.com)",
    )
    rate_limit_per_sec: int = Field(default=10, gt=0, description="Maximum SEC requests per second")


class WatcherSettings(BaseModel):
    """Drop-directory file watcher and write detection configurations."""

    poll_interval_seconds: float = Field(default=1.0, gt=0.0, description="Fallback polling check interval in seconds")
    write_detection_interval_seconds: float = Field(
        default=1.0, gt=0.0, description="Sampling delay to detect complete file writes"
    )
    stability_checks: int = Field(default=2, ge=1, description="Required consecutive unchanged size readings")
    supported_extensions: list[str] = Field(
        default=[".pdf", ".htm", ".html", ".json", ".txt"],
        description="Supported raw file extensions for ingestion",
    )


# -----------------------------------------------------------------------------
# Root Settings Class
# -----------------------------------------------------------------------------


class Settings(BaseModel):
    """Consolidated configuration settings for the entire corpus-analyst microservice mesh."""

    app: AppSettings = Field(default_factory=AppSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    query: QuerySettings = Field(default_factory=QuerySettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    sec: SECSettings = Field(default_factory=SECSettings)
    watcher: WatcherSettings = Field(default_factory=WatcherSettings)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Settings:
        """Load settings by merging default values, optional YAML file, and environment variables.

        Order of precedence (lowest to highest):
        1. Class field defaults
        2. YAML configuration file (if specified or found at default path)
        3. Environment variables

        Args:
            config_path: Path to config.yaml. If None, checks CONFIG_PATH env or config/config.yaml.

        Returns:
            Fully resolved and validated Settings instance.
        """
        raw_data: dict[str, Any] = {}

        # 1. Determine config path
        resolved_path = config_path or os.environ.get("CONFIG_PATH", "config/config.yaml")
        path_obj = Path(resolved_path)

        if path_obj.is_file():
            try:
                with open(path_obj, "r", encoding="utf-8") as f:
                    file_content = yaml.safe_load(f) or {}
                    if isinstance(file_content, dict):
                        raw_data = file_content
                    else:
                        logger.warning("Config file %s did not contain a dictionary; ignoring.", resolved_path)
            except Exception as e:
                logger.error("Failed to parse config YAML at %s: %s", resolved_path, e)
                raise

        # Helper to safely navigate nested dicts
        def _get_subdict(key: str) -> dict[str, Any]:
            sub = raw_data.get(key, {})
            return sub if isinstance(sub, dict) else {}

        app_dict = _get_subdict("app")
        paths_dict = _get_subdict("paths")
        chunking_dict = _get_subdict("chunking")
        storage_dict = _get_subdict("storage")
        query_dict = _get_subdict("query")
        llm_dict = _get_subdict("llm")
        sec_dict = _get_subdict("sec")
        watcher_dict = _get_subdict("watcher")

        # 2. Apply Environment Variable Overrides
        if env_val := os.environ.get("APP_ENV"):
            app_dict["env"] = env_val
        if env_val := os.environ.get("LOG_LEVEL"):
            app_dict["log_level"] = env_val
        if env_val := os.environ.get("DEFAULT_DOMAIN"):
            app_dict["default_domain"] = env_val

        if env_val := os.environ.get("DATA_LAKE_PATH"):
            paths_dict["lake_path"] = env_val
        if env_val := os.environ.get("DATA_INCOMING_PATH"):
            paths_dict["incoming_path"] = env_val
        if env_val := os.environ.get("DATA_PROCESSED_PATH"):
            paths_dict["processed_path"] = env_val
        if env_val := os.environ.get("DATA_FAILED_PATH"):
            paths_dict["failed_path"] = env_val
        if env_val := os.environ.get("MODEL_CACHE_DIR"):
            paths_dict["model_cache_dir"] = env_val

        if env_val := os.environ.get("MAX_CHUNK_TOKENS"):
            chunking_dict["max_chunk_tokens"] = int(env_val)
        if env_val := os.environ.get("CHUNK_OVERLAP_TOKENS"):
            chunking_dict["chunk_overlap_tokens"] = int(env_val)

        if env_val := os.environ.get("AZURE_STORAGE_CONNECTION_STRING"):
            storage_dict["azure_storage_connection_string"] = env_val
        if env_val := os.environ.get("AZURE_CONTAINER_NAME"):
            storage_dict["azure_container_name"] = env_val
        if env_val := os.environ.get("AZURITE_EMULATOR_ENABLED"):
            storage_dict["azurite_emulator_enabled"] = env_val.lower() in ("true", "1", "yes")

        if env_val := os.environ.get("QUERY_ENGINE_HOST"):
            query_dict["host"] = env_val
        if env_val := os.environ.get("QUERY_ENGINE_PORT"):
            query_dict["port"] = int(env_val)
        if env_val := os.environ.get("DUCKDB_PATH"):
            query_dict["duckdb_path"] = env_val
        if env_val := os.environ.get("DEFAULT_TOP_K"):
            query_dict["default_top_k"] = int(env_val)
        if env_val := os.environ.get("SIMILARITY_THRESHOLD"):
            query_dict["similarity_threshold"] = float(env_val)

        if env_val := os.environ.get("LLM_PROVIDER"):
            llm_dict["provider"] = env_val
        if env_val := os.environ.get("GEMINI_API_KEY"):
            llm_dict["gemini_api_key"] = env_val
        if env_val := os.environ.get("GEMINI_MODEL"):
            llm_dict["gemini_model"] = env_val
        if env_val := os.environ.get("OLLAMA_BASE_URL"):
            llm_dict["ollama_base_url"] = env_val
        if env_val := os.environ.get("OLLAMA_MODEL"):
            llm_dict["ollama_model"] = env_val

        if env_val := os.environ.get("SEC_USER_AGENT"):
            sec_dict["user_agent"] = env_val

        if env_val := os.environ.get("WATCHER_POLL_INTERVAL"):
            watcher_dict["poll_interval_seconds"] = float(env_val)
        if env_val := os.environ.get("WATCHER_WRITE_INTERVAL"):
            watcher_dict["write_detection_interval_seconds"] = float(env_val)
        if env_val := os.environ.get("WATCHER_STABILITY_CHECKS"):
            watcher_dict["stability_checks"] = int(env_val)

        return cls(
            app=AppSettings(**app_dict),
            paths=PathSettings(**paths_dict),
            chunking=ChunkingSettings(**chunking_dict),
            storage=StorageSettings(**storage_dict),
            query=QuerySettings(**query_dict),
            llm=LLMSettings(**llm_dict),
            sec=SECSettings(**sec_dict),
            watcher=WatcherSettings(**watcher_dict),
        )


def load_model_profiles(path: str | Path | None = None) -> ModelRegistryConfig:
    """Load dynamic domain embedding profiles from models.json.

    Args:
        path: Path to models.json. If None, checks MODELS_CONFIG_PATH env or config/models.json.

    Returns:
        ModelRegistryConfig model containing verified domain profiles.

    Raises:
        FileNotFoundError: If the models specification file is missing.
        ValueError: If the file contents cannot be parsed into ModelRegistryConfig.
    """
    resolved_path = path or os.environ.get("MODELS_CONFIG_PATH", "config/models.json")
    path_obj = Path(resolved_path)

    if not path_obj.is_file():
        raise FileNotFoundError(f"Model profiles specification not found at: {resolved_path}")

    with open(path_obj, "r", encoding="utf-8") as f:
        data = json.load(f)

    return ModelRegistryConfig(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Dependency injection provider for application settings.

    Caches the settings instance for lifecycle efficiency while permitting
    overrides during testing via `get_settings.cache_clear()`.

    Returns:
        Loaded Settings instance.
    """
    return Settings.load()


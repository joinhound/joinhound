# SPDX-License-Identifier: Apache-2.0

"""Application configuration loaded from YAML and environment variables."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, cast

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """A configuration file cannot be loaded."""


class AclConfig(BaseModel):
    """Roles allowed to read a document collection."""

    roles: list[str] = Field(default_factory=list)


class PostgresSourceConfig(BaseModel):
    """Connection settings for a read-only PostgreSQL source."""

    type: Literal["postgres"]
    dsn: str
    schemas: list[str] = Field(default_factory=lambda: ["public"])
    exclude_tables: list[str] = Field(default_factory=list)
    statement_timeout_ms: int = 5000


class S3SourceConfig(BaseModel):
    """Connection settings for an S3-compatible document source."""

    type: Literal["s3"]
    bucket: str
    prefix: str = ""
    region: str | None = None
    acl: AclConfig = Field(default_factory=AclConfig)


SourceConfig = Annotated[PostgresSourceConfig | S3SourceConfig, Field(discriminator="type")]


class EmbeddingsConfig(BaseModel):
    """Selected embedding provider."""

    provider: str
    model: str
    dim: int


class JudgeConfig(BaseModel):
    """Selected relationship judge."""

    provider: str
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    redact: bool = False
    sensitive_columns: list[str] = Field(default_factory=list)


class ProfilerConfig(BaseModel):
    """Thresholds used while proposing relationships."""

    sample_values: int = 10000
    containment_threshold: float = 0.5
    min_distinct: int = 20
    year_min: int = 1900
    year_max: int = 2100
    year_share: float = 0.5
    long_text_length: int = 200
    integer_uniqueness: float = 0.99
    integer_containment: float = 0.95
    integer_min_distinct: int = 1000
    auto_approve: float | None = None


class EngineConfig(BaseModel):
    """Limits for one context query."""

    seeds_k: int = 10
    max_depth: int = 3
    beam_width: int = 20
    fanout: int = 25
    depth_decay: float = 0.8
    budget_tokens: int = 4000
    timeout_ms: int = 10000


class ServerConfig(BaseModel):
    """MCP server transport and its development credential."""

    transport: Literal["stdio", "http"] = "stdio"
    http_port: int = 8787
    auth_token: str | None = None


class AppConfig(BaseSettings):
    """The complete runtime configuration."""

    model_config = SettingsConfigDict(extra="forbid")

    mode: Literal["sidecar", "co_located"] = "sidecar"
    kg_database: str
    sources: dict[str, SourceConfig]
    embeddings: EmbeddingsConfig
    judge: JudgeConfig
    profiler: ProfilerConfig = Field(default_factory=ProfilerConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> AppConfig:
    """Load YAML configuration, substituting ${VAR} from the environment."""
    environment = os.environ if environ is None else environ
    loaded = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    if not isinstance(loaded, dict):
        raise ConfigError("Configuration must be a YAML mapping")
    expanded = _expand(loaded, environment)
    try:
        return AppConfig.model_validate(expanded)
    except ValidationError as error:
        raise ConfigError(str(error)) from error


def _expand(value: object, environ: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return _ENV_REFERENCE.sub(lambda match: _lookup(match.group(1), environ), value)
    if isinstance(value, list):
        return [_expand(item, environ) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand(item, environ) for key, item in value.items()}
    return value


def _lookup(name: str, environ: Mapping[str, str]) -> str:
    try:
        return environ[name]
    except KeyError as error:
        raise ConfigError(f"Missing environment variable {name}") from error

# SPDX-License-Identifier: Apache-2.0

"""Tests for YAML configuration and environment substitution."""

from pathlib import Path

import pytest

from joinhound.core.config import ConfigError, load_config

_CONFIG = """
mode: sidecar
kg_database: ${KG_DSN}
sources:
  main:
    type: postgres
    dsn: ${PG_READONLY_DSN}
    schemas: [public]
    exclude_tables: [audit_log]
    statement_timeout_ms: 5000
  contracts:
    type: s3
    bucket: acme-contracts
    prefix: 2025/
    region: eu-north-1
    acl: {roles: [legal, sales]}
embeddings: {provider: local, model: BAAI/bge-m3, dim: 1024}
judge:
  provider: openai
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${JUDGE_MODEL}
profiler:
  sample_values: 10000
  containment_threshold: 0.5
  auto_approve: null
engine:
  seeds_k: 10
  max_depth: 3
  beam_width: 20
  fanout: 25
  depth_decay: 0.8
  budget_tokens: 4000
  timeout_ms: 10000
server:
  transport: stdio
  http_port: 8787
  auth_token: ${MCP_TOKEN}

"""


def test_config_substitutes_environment(tmp_path: Path) -> None:
    path = tmp_path / "joinhound.yaml"
    path.write_text(_CONFIG, encoding="utf-8")

    config = load_config(
        path,
        {
            "KG_DSN": "postgresql://kg",
            "PG_READONLY_DSN": "postgresql://source",
            "LLM_BASE_URL": "https://api.anthropic.com/v1/",
            "LLM_API_KEY": "secret",
            "JUDGE_MODEL": "claude-sonnet-5-5",
            "MCP_TOKEN": "token",
        },
    )

    assert config.mode == "sidecar"
    assert config.kg_database == "postgresql://kg"
    assert config.sources["main"].type == "postgres"
    assert config.sources["main"].dsn == "postgresql://source"
    assert config.sources["contracts"].type == "s3"
    assert config.sources["contracts"].acl.roles == ["legal", "sales"]
    assert config.judge.api_key == "secret"


def test_missing_environment_variable_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "joinhound.yaml"
    path.write_text("kg_database: ${MISSING}\nsources: {}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="MISSING"):
        load_config(path, {})


def test_invalid_mode_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "joinhound.yaml"
    path.write_text(
        "mode: write\nkg_database: kg\nsources: {}\n"
        "embeddings: {provider: local, model: m, dim: 3}\n"
        "judge: {provider: none}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(path, {})

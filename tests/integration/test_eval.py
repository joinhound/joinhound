# SPDX-License-Identifier: Apache-2.0

"""The Pagila evaluation stub: gold foreign keys and an empty score."""

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer
from typer.testing import CliRunner

from joinhound.cli import app

_PAGILA_REF = "ce6e114236bb828e5ec0dc835f65f1bf1b9179f5"
_GOLD = Path(__file__).resolve().parents[1] / "eval" / "gold" / "pagila_fk.json"
_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture(scope="module")
def pagila_dsn() -> Iterator[str]:
    with PostgresContainer(
        "pgvector/pgvector:pg18",
        username="postgres",
        password="postgres",
        dbname="pagila",
        driver=None,
    ) as postgres:
        _load_pagila(postgres)
        yield postgres.get_connection_url(driver=None)


def test_prepare_drops_foreign_keys_on_a_copy(pagila_dsn: str, tmp_path: Path) -> None:
    original = _foreign_key_count(pagila_dsn)
    gold_path = tmp_path / "pagila_fk.json"
    subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "prepare_pagila_eval.py"),
            "--dsn",
            pagila_dsn,
            "--gold",
            str(gold_path),
        ],
        check=True,
    )

    written = json.loads(gold_path.read_text(encoding="utf-8"))
    committed = json.loads(_GOLD.read_text(encoding="utf-8"))
    assert written == committed
    assert original > 0
    assert _foreign_key_count(pagila_dsn) == original
    assert _foreign_key_count(f"{pagila_dsn}_nofk") == 0


def test_eval_prints_zero_recall_for_an_empty_ontology(pagila_dsn: str, tmp_path: Path) -> None:
    config = tmp_path / "joinhound.yaml"
    config.write_text(
        "\n".join(
            [
                "mode: sidecar",
                f"kg_database: {pagila_dsn}",
                "sources: {}",
                "embeddings:",
                "  provider: none",
                "  model: none",
                "  dim: 1024",
                "judge:",
                "  provider: none",
                "",
            ]
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["eval", "--config", str(config), "--gold", str(_GOLD)],
    )

    assert result.exit_code == 0, result.output
    assert "recall 0.000" in result.output


def _foreign_key_count(dsn: str) -> int:
    query = """
        SELECT count(*)
        FROM pg_constraint AS constraint_
        JOIN pg_class AS relation ON relation.oid = constraint_.conrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE constraint_.contype = 'f'
          AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    """
    with psycopg.connect(dsn) as connection:
        row = connection.execute(query).fetchone()
    if row is None:
        return 0
    return int(row[0])


def _load_pagila(postgres: PostgresContainer) -> None:
    container_id = postgres.get_wrapped_container().id
    for name in ("pagila-schema.sql", "pagila-data.sql"):
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container_id,
                "psql",
                "--username",
                "postgres",
                "--dbname",
                "pagila",
                "--set",
                "ON_ERROR_STOP=1",
            ],
            input=_pagila_file(name).read_bytes(),
            check=True,
        )


def _pagila_file(name: str) -> Path:
    cache = _ROOT / "cache" / "pagila" / _PAGILA_REF
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    if path.is_file() and path.stat().st_size > 0:
        return path
    url = f"https://raw.githubusercontent.com/devrimgunduz/pagila/{_PAGILA_REF}/{name}"
    subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location", "--output", str(path), url],
        check=True,
    )
    return path

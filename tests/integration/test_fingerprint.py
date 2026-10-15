# SPDX-License-Identifier: Apache-2.0

"""Profiling Pagila writes kg.columns in under a minute."""

import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from testcontainers.community.postgres import PostgresContainer

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import PostgresSourceConfig
from joinhound.index.columns import save_column_profiles
from joinhound.index.schema import apply_schema
from joinhound.profiler.fingerprint import profile_columns

_PAGILA_REF = "ce6e114236bb828e5ec0dc835f65f1bf1b9179f5"


@pytest.fixture(scope="module")
def databases() -> Iterator[tuple[str, str]]:
    with PostgresContainer(
        "pgvector/pgvector:pg18",
        username="postgres",
        password="postgres",
        dbname="pagila",
        driver=None,
    ) as postgres:
        _load_pagila(postgres)
        pagila = postgres.get_connection_url(driver=None)
        _create_database(pagila, "joinhound")
        yield pagila, _replace_database(pagila, "joinhound")


def test_pagila_profiles_fit_in_kg_columns(databases: tuple[str, str]) -> None:
    pagila_dsn, kg_dsn = databases
    apply_schema(kg_dsn)
    source = PostgresSource(
        "pagila",
        PostgresSourceConfig(
            type="postgres",
            dsn=pagila_dsn,
            schemas=["public"],
            statement_timeout_ms=5000,
        ),
    )
    started = time.perf_counter()
    with source:
        profiles = profile_columns(source)
        save_column_profiles(kg_dsn, "pagila", profiles)
        save_column_profiles(kg_dsn, "pagila", profiles)
    elapsed = time.perf_counter() - started

    assert elapsed < 60, f"profiling took {elapsed:.1f}s"
    with psycopg.connect(kg_dsn, row_factory=dict_row) as connection:
        count = connection.execute("SELECT count(*) AS count FROM kg.columns").fetchone()
        language = connection.execute(
            """
            SELECT type_class, pattern, uniqueness, octet_length(minhash) AS minhash_bytes
            FROM kg.columns
            WHERE collection_id = 'pg://pagila/public.language'
              AND column_name = 'name'
            """
        ).fetchone()
    assert count is not None
    assert int(count["count"]) == len(profiles)
    assert len(profiles) > 20
    assert language is not None
    assert language["type_class"] == "text"
    assert language["pattern"] == "A"
    assert language["uniqueness"] == 1
    assert language["minhash_bytes"] == 512


def _create_database(dsn: str, name: str) -> None:
    admin = _replace_database(dsn, "postgres")
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _replace_database(dsn: str, name: str) -> str:
    parsed = urlsplit(dsn)
    return urlunsplit(parsed._replace(path=f"/{name}"))


def _load_pagila(postgres: PostgresContainer) -> None:
    container_id = postgres.get_wrapped_container().id
    root = Path(__file__).resolve().parents[2]
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
            input=_pagila_file(root, name).read_bytes(),
            check=True,
        )


def _pagila_file(root: Path, name: str) -> Path:
    cache = root / "cache" / "pagila" / _PAGILA_REF
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

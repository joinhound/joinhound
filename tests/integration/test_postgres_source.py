# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the PostgreSQL source on Pagila."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import PostgresSourceConfig
from joinhound.core.models import DeclaredFK
from joinhound.core.uri import parse_uri
from joinhound.testing.contracts import check_tabular_source

_PAGILA_REF = "ce6e114236bb828e5ec0dc835f65f1bf1b9179f5"
_LANGUAGE = "pg://pagila/public.language"


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
        dsn = postgres.get_connection_url(driver=None)
        _create_key_tables(dsn)
        yield dsn


def test_pagila_contract(pagila_dsn: str) -> None:
    with _source(pagila_dsn) as source:
        check_tabular_source(
            source,
            collection_id=_LANGUAGE,
            column="name",
            value="English",
            key={"language_id": 1},
        )


def test_declared_film_language_link(pagila_dsn: str) -> None:
    with _source(pagila_dsn) as source:
        links = source.declared_links()

    assert (
        DeclaredFK(
            src_collection="pg://pagila/public.film",
            src_columns=["language_id"],
            dst_collection=_LANGUAGE,
            dst_columns=["language_id"],
        )
        in links
    )
    with _source(pagila_dsn) as source:
        collections = {item.collection_id for item in source.list_collections()}
    assert "pg://pagila/public.film_list" in collections


def test_session_rejects_writes(pagila_dsn: str) -> None:
    with _source(pagila_dsn) as source:
        with source.connection() as connection:
            settings = connection.execute(
                """
                SELECT current_setting('application_name') AS application_name,
                       current_setting('default_transaction_read_only') AS read_only,
                       current_setting('statement_timeout') AS statement_timeout
                """
            ).fetchone()
            assert settings is not None
            assert settings["application_name"] == "joinhound"
            assert settings["read_only"] == "on"
            assert settings["statement_timeout"] in {"5s", "5000ms"}
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                connection.execute(
                    "INSERT INTO public.language (language_id, name) VALUES (99, 'blocked')"
                )


def test_key_selection_chain(pagila_dsn: str) -> None:
    with _source(pagila_dsn) as source:
        primary = source.fetch_by_keys("pg://pagila/public.key_pk", [{"id": 1}])
        unique = source.find_values("pg://pagila/public.key_unique", "label", ["unique"], "exact")
        nullable = source.find_values(
            "pg://pagila/public.key_nullable_unique",
            "label",
            ["nullable"],
            "exact",
        )
        heap = source.find_values("pg://pagila/public.key_heap", "label", ["heap"], "exact")
        normalized = source.find_values(
            _LANGUAGE,
            "name",
            ["english"],
            "normalized",
            normalize_sql="lower(name)",
        )

    assert primary[0].pk == {"id": 1}
    assert parse_uri(primary[0].uri).unstable is False
    assert unique[0].pk == {"code": "abc"}
    assert set(nullable[0].pk) == {"ctid"}
    assert set(heap[0].pk) == {"ctid"}
    fetched = source_fetch_heap(pagila_dsn, heap[0].pk)
    parsed = parse_uri(fetched)
    assert parsed.unstable is True
    assert parsed.row_hash
    assert normalized[0].value == "English"


def source_fetch_heap(dsn: str, key: dict[str, object]) -> str:
    with _source(dsn) as source:
        records = source.fetch_by_keys("pg://pagila/public.key_heap", [key])
    return records[0].uri


def _source(dsn: str) -> PostgresSource:
    return PostgresSource(
        "pagila",
        PostgresSourceConfig(
            type="postgres",
            dsn=dsn,
            schemas=["public"],
            statement_timeout_ms=5000,
        ),
    )


def _create_key_tables(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE key_pk (id int PRIMARY KEY, label text);
            INSERT INTO key_pk VALUES (1, 'pk');
            CREATE TABLE key_unique (code text NOT NULL UNIQUE, label text);
            INSERT INTO key_unique VALUES ('abc', 'unique');
            CREATE TABLE key_nullable_unique (code text UNIQUE, label text NOT NULL);
            INSERT INTO key_nullable_unique VALUES ('n', 'nullable');
            CREATE TABLE key_heap (label text);
            INSERT INTO key_heap VALUES ('heap');
            """
        )


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
    cache = Path(__file__).resolve().parents[2] / "cache" / "pagila" / _PAGILA_REF
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

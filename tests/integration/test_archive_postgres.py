# SPDX-License-Identifier: Apache-2.0

"""The archive comparison holds when the catalog is a Postgres database."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from joinhound.archive_eval import ArchiveDataset, load_archive, measure
from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import PostgresSourceConfig

_ROOT = Path(__file__).resolve().parents[1] / "eval" / "archives"


@pytest.fixture(scope="module")
def archive_dsn() -> Iterator[str]:
    dataset = load_archive(_ROOT / "historical-document-archives.json")
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="archives",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        _load(dsn, dataset)
        yield dsn


def test_postgres_catalog_misses_the_highlight_files(archive_dsn: str) -> None:
    dataset = load_archive(_ROOT / "historical-document-archives.json")
    with PostgresSource(
        "archives",
        PostgresSourceConfig(type="postgres", dsn=archive_dsn, schemas=["public"]),
    ) as source:
        gap = measure(source, dataset)

    assert gap.catalog_without == 1
    assert gap.catalog_with == 1
    assert gap.file_without == 0
    assert gap.file_with == 1
    assert gap.bridge_without == 0
    assert gap.bridge_with == 1


def _load(dsn: str, dataset: ArchiveDataset) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE document_authors (
              id int PRIMARY KEY,
              full_name text NOT NULL,
              birth_year int NOT NULL,
              death_year int
            );
            CREATE TABLE document_eras (
              id int PRIMARY KEY,
              era_name text NOT NULL,
              start_year int NOT NULL,
              end_year int NOT NULL
            );
            CREATE TABLE document_materials (
              id int PRIMARY KEY,
              material_type text NOT NULL,
              durability_score int NOT NULL,
              source text NOT NULL,
              sustainability_score int NOT NULL
            );
            CREATE TABLE documents (
              id int PRIMARY KEY,
              title text NOT NULL,
              document_era_id int NOT NULL REFERENCES document_eras (id),
              author_id int NOT NULL REFERENCES document_authors (id),
              format text NOT NULL,
              condition text NOT NULL,
              archive_code text NOT NULL UNIQUE
            );
            CREATE TABLE document_events (
              id int PRIMARY KEY,
              document_id int NOT NULL REFERENCES documents (id),
              event_type text NOT NULL,
              event_date date NOT NULL,
              attendee_count int NOT NULL
            )
            """
        )
        _insert(
            connection,
            "document_authors",
            ("id", "full_name", "birth_year", "death_year"),
            dataset.rows["document_authors"],
        )
        _insert(
            connection,
            "document_eras",
            ("id", "era_name", "start_year", "end_year"),
            dataset.rows["document_eras"],
        )
        _insert(
            connection,
            "document_materials",
            ("id", "material_type", "durability_score", "source", "sustainability_score"),
            dataset.rows["document_materials"],
        )
        _insert(
            connection,
            "documents",
            (
                "id",
                "title",
                "document_era_id",
                "author_id",
                "format",
                "condition",
                "archive_code",
            ),
            dataset.rows["documents"],
        )
        _insert(
            connection,
            "document_events",
            ("id", "document_id", "event_type", "event_date", "attendee_count"),
            dataset.rows["document_events"],
        )


def _insert(
    connection: psycopg.Connection[tuple[object, ...]],
    table: str,
    columns: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    names = ", ".join(columns)
    placeholders = ", ".join("%s" for _ in columns)
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
            [tuple(row[column] for column in columns) for row in rows],
        )

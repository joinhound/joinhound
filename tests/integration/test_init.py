# SPDX-License-Identifier: Apache-2.0

"""Integration tests for joinhound init."""

from pathlib import Path

import psycopg
from testcontainers.community.postgres import PostgresContainer
from typer.testing import CliRunner

from joinhound.cli import app
from joinhound.index.schema import apply_schema

runner = CliRunner()

_TABLES = {
    "chunks",
    "collections",
    "columns",
    "documents",
    "links",
    "sources",
    "value_index",
    "value_sync",
}

_INDEXES = {
    "kg_chunks_embedding_hnsw",
    "kg_chunks_text_trgm",
    "kg_chunks_tsv",
    "kg_value_index_embedding_hnsw",
    "kg_value_index_lookup",
    "kg_value_index_norm_value_trgm",
}


def test_init_is_idempotent_and_enables_extensions(tmp_path: Path) -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        apply_schema(dsn)
        config = tmp_path / "joinhound.yaml"
        config.write_text(
            "\n".join(
                [
                    "mode: sidecar",
                    f"kg_database: {dsn}",
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
        result = runner.invoke(app, ["init", "--config", str(config)])

        assert result.exit_code == 0, result.output
        with psycopg.connect(dsn) as connection:
            extensions = connection.execute(
                "SELECT extname FROM pg_extension WHERE extname IN ('pg_trgm', 'vector')"
            ).fetchall()
            tables = connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'kg'
                """
            ).fetchall()
            indexes = connection.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'kg'"
            ).fetchall()
            embedding = connection.execute(
                """
                SELECT format_type(attribute.atttypid, attribute.atttypmod)
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'kg'
                  AND relation.relname = 'value_index'
                  AND attribute.attname = 'embedding'
                """
            ).fetchone()
            applied = connection.execute("SELECT count(*) FROM _yoyo_migration").fetchone()

        assert {row[0] for row in extensions} == {"pg_trgm", "vector"}
        assert {row[0] for row in tables} == _TABLES
        assert _INDEXES <= {row[0] for row in indexes}
        assert embedding == ("vector(1024)",)
        assert applied == (2,)

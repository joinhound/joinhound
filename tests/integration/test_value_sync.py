# SPDX-License-Identifier: Apache-2.0

"""A changed source row appears in kg.value_index after sync."""

import psycopg
from testcontainers.community.postgres import PostgresContainer

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import PostgresSourceConfig
from joinhound.core.models import LinkDraft
from joinhound.index.links import save_links
from joinhound.index.schema import apply_schema
from joinhound.index.values import sync_values


def test_a_changed_row_is_indexed_after_sync() -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        apply_schema(dsn)
        _create_tables(dsn)
        _approve(dsn)
        source = _source(dsn)
        try:
            assert sync_values(dsn, "app", source) == 2
            assert _values(dsn, "public.customer", "email") == ["ada@example.com"]
            assert _values(dsn, "public.orders", "code") == ["prd-1"]

            with psycopg.connect(dsn) as connection:
                connection.execute(
                    "UPDATE public.customer SET email = 'Grace@Example.com' WHERE id = 1"
                )
                connection.execute(
                    "UPDATE public.orders SET code = 'PRD-2', updated_at = now() WHERE id = 1"
                )
                connection.commit()
            assert sync_values(dsn, "app", source) == 2
            assert _values(dsn, "public.customer", "email") == ["grace@example.com"]
            assert _values(dsn, "public.orders", "code") == ["prd-2"]
            assert sync_values(dsn, "app", source) == 0
        finally:
            source.close()


def _create_tables(dsn: str) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            CREATE TABLE public.customer (id int PRIMARY KEY, email text);
            INSERT INTO public.customer VALUES (1, 'Ada@Example.com');
            CREATE TABLE public.orders (
              id int PRIMARY KEY,
              code text,
              updated_at timestamptz NOT NULL DEFAULT now()
            );
            INSERT INTO public.orders (id, code) VALUES (1, 'PRD-1');
            """
        )
        connection.commit()


def _approve(dsn: str) -> None:
    save_links(
        dsn,
        [
            LinkDraft(
                link_id="customer-email",
                src_collection="pg://app/public.customer",
                src_column="email",
                dst_collection="pg://app/public.customer",
                dst_column="email",
                match_type="fuzzy",
                origin="discovered",
                confidence=0.9,
                status="approved",
            ),
            LinkDraft(
                link_id="order-code",
                src_collection="pg://app/public.orders",
                src_column="code",
                dst_collection="pg://app/public.orders",
                dst_column="code",
                match_type="semantic",
                origin="discovered",
                confidence=0.9,
                status="approved",
                normalize_sql="fold",
            ),
        ],
    )


def _source(dsn: str) -> PostgresSource:
    return PostgresSource(
        "app",
        PostgresSourceConfig(type="postgres", dsn=dsn, statement_timeout_ms=30_000),
    )


def _values(dsn: str, table: str, column: str) -> list[str]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            """
            SELECT norm_value
            FROM kg.value_index
            WHERE collection_id = %s AND column_name = %s
            ORDER BY norm_value
            """,
            (f"pg://app/{table}", column),
        ).fetchall()
    return [str(row[0]) for row in rows]

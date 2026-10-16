# SPDX-License-Identifier: Apache-2.0

"""Fuzzy resolution uses pg_trgm on kg.value_index."""

import psycopg
from psycopg.types.json import Json
from testcontainers.community.postgres import PostgresContainer

from joinhound.core.models import Link, QueryContext
from joinhound.index.schema import apply_schema
from joinhound.matchers.fuzzy import FuzzyMatcher
from joinhound.testing.memory import MemoryTabularSource


def test_pg_trgm_returns_a_close_value() -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        apply_schema(dsn)
        with psycopg.connect(dsn) as connection:
            connection.execute(
                """
                INSERT INTO kg.value_index (collection_id, column_name, pk, norm_value)
                VALUES (%s, %s, %s, %s)
                """,
                ("customers", "name", Json({"id": 1}), "ada lovlace"),
            )
            connection.commit()
        matcher = FuzzyMatcher(MemoryTabularSource({}), dsn)
        found = matcher.resolve(
            Link(
                link_id="orders.name",
                match_type="fuzzy",
                src_collection="orders",
                src_column="name",
                dst_collection="customers",
                dst_column="name",
            ),
            ["Ada Lovelace"],
            QueryContext(),
        )

        assert found
        assert found[0].pk == {"id": 1}
        assert found[0].value == "Ada Lovelace"
        assert found[0].score >= 0.6

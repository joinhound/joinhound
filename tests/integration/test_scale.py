# SPDX-License-Identifier: Apache-2.0

"""Indexed lookup on ten million rows stays under the p95 budget."""

import math
import time

import psycopg
from testcontainers.community.postgres import PostgresContainer

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import EngineConfig, PostgresSourceConfig
from joinhound.engine.context import get_context
from joinhound.engine.dictionary import ValueDictionary

_ROWS = 10_000_000
_CODE = "C424242"


def test_indexed_lookup_on_ten_million_rows_is_under_two_seconds() -> None:
    with PostgresContainer(
        "postgres:16-alpine",
        username="postgres",
        password="postgres",
        dbname="bench",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        _load(dsn)
        samples = _samples(dsn)

    assert len(samples) == 20
    assert _p95(samples) < 2


def _load(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE UNLOGGED TABLE bench (
                id bigint PRIMARY KEY,
                code text NOT NULL,
                note text NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO bench (id, code, note)
            SELECT i, 'C' || i::text, 'note'
            FROM generate_series(1, %s) AS i
            """,
            (_ROWS,),
        )
        connection.execute("CREATE INDEX bench_code ON bench (code)")
        connection.execute("ANALYZE bench")


def _samples(dsn: str) -> list[float]:
    dictionary = ValueDictionary()
    dictionary.add("pg://bench/public.bench", "code", _CODE)
    dictionary.freeze()
    samples: list[float] = []
    config = PostgresSourceConfig(
        type="postgres",
        dsn=dsn,
        schemas=["public"],
        statement_timeout_ms=30_000,
    )
    with PostgresSource("bench", config) as source:
        for _ in range(20):
            started = time.perf_counter()
            result = get_context(
                _CODE,
                source,
                [],
                {},
                EngineConfig(timeout_ms=2000),
                max_depth=0,
                dictionary=dictionary,
            )
            samples.append(time.perf_counter() - started)
            assert any(node.content.get("code") == _CODE for node in result.nodes)
    return samples


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]

# SPDX-License-Identifier: Apache-2.0

"""Copy values of approved fuzzy and semantic columns into kg.value_index."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from joinhound.core.models import Cursor
from joinhound.core.protocols import Embedder, TabularSource
from joinhound.index.normalize import apply, names

_MODULUS = 32


@dataclass(frozen=True)
class _Column:
    collection_id: str
    column: str
    expression: str


def sync_values(
    dsn: str,
    source_name: str,
    source: TabularSource,
    embedder: Embedder | None = None,
    *,
    force: bool = False,
) -> int:
    """Refresh indexed values for one source. Return how many rows were written."""
    written = 0
    for column in _columns(dsn, source_name):
        stored = None if force else _read_cursor(dsn, column)
        rows = list(source.scan_column(column.collection_id, column.column, stored))
        scanned = _scanned_cursor(source)
        written += _write(dsn, column, stored, scanned, rows, embedder)
    return written


def _scanned_cursor(source: TabularSource) -> Cursor | None:
    cursor = getattr(source, "scan_cursor", None)
    if isinstance(cursor, Cursor):
        return cursor
    return None


def _columns(dsn: str, source_name: str) -> list[_Column]:
    prefix = f"pg://{source_name}/"
    found: dict[tuple[str, str], str] = {}
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        present = connection.execute("SELECT to_regclass('kg.links') AS regclass").fetchone()
        if present is None or present["regclass"] is None:
            return []
        rows = connection.execute(
            """
            SELECT src_collection, src_column, dst_collection, dst_column, normalize_sql
            FROM kg.links
            WHERE status = 'approved' AND match_type IN ('fuzzy', 'semantic')
            """
        ).fetchall()
    for row in rows:
        expression = _expression(row["normalize_sql"])
        destination = row["dst_column"]
        pairs = (
            (str(row["src_collection"]), str(row["src_column"])),
            (str(row["dst_collection"]), None if destination is None else str(destination)),
        )
        for collection_id, column in pairs:
            if column is None or not collection_id.startswith(prefix):
                continue
            found.setdefault((collection_id, column), expression)
    return [
        _Column(collection_id, column, expression)
        for (collection_id, column), expression in found.items()
    ]


def _expression(raw: object) -> str:
    if isinstance(raw, str) and raw in names():
        return raw
    return "fold"


def _read_cursor(dsn: str, column: _Column) -> Cursor | None:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        present = connection.execute("SELECT to_regclass('kg.value_sync') AS regclass").fetchone()
        if present is None or present["regclass"] is None:
            return None
        row = connection.execute(
            """
            SELECT cursor FROM kg.value_sync
            WHERE collection_id = %s AND column_name = %s
            """,
            (column.collection_id, column.column),
        ).fetchone()
    if row is None:
        return None
    return Cursor(value=str(row["cursor"]))


def _write(
    dsn: str,
    column: _Column,
    stored: Cursor | None,
    scanned: Cursor | None,
    rows: Sequence[tuple[dict[str, object], str]],
    embedder: Embedder | None,
) -> int:
    if stored is not None and scanned is not None and stored.value == scanned.value:
        return 0
    mode = _mode(scanned)
    with psycopg.connect(dsn) as connection:
        if mode == "blocks":
            changed = _changed_ids(stored, scanned)
            if changed:
                connection.execute(
                    """
                    DELETE FROM kg.value_index
                    WHERE collection_id = %s
                      AND column_name = %s
                      AND mod(abs(hashtext(pk::text)::bigint), %s) = ANY(%s)
                    """,
                    (column.collection_id, column.column, _MODULUS, changed),
                )
            count = _insert(connection, column, rows, embedder)
        elif mode == "updated_at":
            count = _upsert(connection, column, rows, embedder)
        else:
            connection.execute(
                "DELETE FROM kg.value_index WHERE collection_id = %s AND column_name = %s",
                (column.collection_id, column.column),
            )
            count = _insert(connection, column, rows, embedder)
        if scanned is not None:
            connection.execute(
                """
                INSERT INTO kg.value_sync (collection_id, column_name, cursor)
                VALUES (%s, %s, %s)
                ON CONFLICT (collection_id, column_name)
                DO UPDATE SET cursor = EXCLUDED.cursor
                """,
                (column.collection_id, column.column, scanned.value),
            )
        connection.commit()
    return count


def _mode(cursor: Cursor | None) -> str:
    if cursor is None:
        return "replace"
    try:
        parsed = json.loads(cursor.value)
    except json.JSONDecodeError:
        return "updated_at"
    if not isinstance(parsed, dict) or "blocks" not in parsed:
        return "updated_at"
    if parsed.get("modulus") == 0:
        return "replace"
    return "blocks"


def _changed_ids(stored: Cursor | None, scanned: Cursor | None) -> list[int]:
    previous = _blocks(stored)
    current = _blocks(scanned)
    names_ = set(previous) | set(current)
    return sorted(int(name) for name in names_ if previous.get(name) != current.get(name))


def _blocks(cursor: Cursor | None) -> dict[str, str]:
    if cursor is None:
        return {}
    parsed = json.loads(cursor.value)
    if not isinstance(parsed, dict):
        return {}
    blocks = parsed.get("blocks")
    if not isinstance(blocks, dict):
        return {}
    return {str(key): str(value) for key, value in blocks.items()}


def _upsert(
    connection: psycopg.Connection[tuple[object, ...]],
    column: _Column,
    rows: Sequence[tuple[dict[str, object], str]],
    embedder: Embedder | None,
) -> int:
    for pk, _value in rows:
        connection.execute(
            """
            DELETE FROM kg.value_index
            WHERE collection_id = %s AND column_name = %s AND pk = %s::jsonb
            """,
            (column.collection_id, column.column, Json(pk)),
        )
    return _insert(connection, column, rows, embedder)


def _insert(
    connection: psycopg.Connection[tuple[object, ...]],
    column: _Column,
    rows: Sequence[tuple[dict[str, object], str]],
    embedder: Embedder | None,
) -> int:
    norms = [apply(column.expression, value) for _pk, value in rows]
    vectors: list[list[float] | None]
    if embedder is None:
        vectors = [None] * len(rows)
    else:
        vectors = [list(vector) for vector in embedder.embed(norms)]
    for (pk, _value), norm, vector in zip(rows, norms, vectors, strict=True):
        if vector is None:
            connection.execute(
                """
                INSERT INTO kg.value_index (collection_id, column_name, pk, norm_value, synced_at)
                VALUES (%s, %s, %s, %s, now())
                """,
                (column.collection_id, column.column, Json(pk), norm),
            )
            continue
        connection.execute(
            """
            INSERT INTO kg.value_index
              (collection_id, column_name, pk, norm_value, embedding, synced_at)
            VALUES (%s, %s, %s, %s, %s::vector, now())
            """,
            (
                column.collection_id,
                column.column,
                Json(pk),
                norm,
                "[" + ",".join(f"{item:.6f}" for item in vector) + "]",
            ),
        )
    return len(rows)

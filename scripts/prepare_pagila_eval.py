# SPDX-License-Identifier: Apache-2.0

"""Copy Pagila, save its foreign keys, and drop them on the copy.

The original database is left unchanged. The copy is named ``<database>_nofk``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

_FK_QUERY = """
    SELECT
      source_namespace.nspname AS schema_name,
      source_relation.relname AS table_name,
      constraint_.conname AS constraint_name,
      (
        SELECT array_agg(attribute.attname ORDER BY columns.ordinality)
        FROM unnest(constraint_.conkey) WITH ORDINALITY AS columns(attnum, ordinality)
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = source_relation.oid
         AND attribute.attnum = columns.attnum
      ) AS columns,
      target_namespace.nspname AS ref_schema,
      target_relation.relname AS ref_table,
      (
        SELECT array_agg(attribute.attname ORDER BY columns.ordinality)
        FROM unnest(constraint_.confkey) WITH ORDINALITY AS columns(attnum, ordinality)
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = target_relation.oid
         AND attribute.attnum = columns.attnum
      ) AS ref_columns
    FROM pg_constraint AS constraint_
    JOIN pg_class AS source_relation ON source_relation.oid = constraint_.conrelid
    JOIN pg_namespace AS source_namespace
      ON source_namespace.oid = source_relation.relnamespace
    JOIN pg_class AS target_relation ON target_relation.oid = constraint_.confrelid
    JOIN pg_namespace AS target_namespace
      ON target_namespace.oid = target_relation.relnamespace
    WHERE constraint_.contype = 'f'
      AND source_namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY source_namespace.nspname, source_relation.relname, constraint_.conname
"""


def prepare(dsn: str, gold_path: Path) -> None:
    """Write gold foreign keys and drop them on a copy of the database."""
    parsed = urlsplit(dsn)
    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError("DSN must name a database")
    copy_name = f"{database}_nofk"
    admin = urlunsplit(parsed._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(copy_name)))
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(copy_name),
                sql.Identifier(database),
            )
        )
    copy_dsn = urlunsplit(parsed._replace(path=f"/{copy_name}"))
    constraints = read_foreign_keys(copy_dsn)
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"constraints": constraints}
    gold_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    drop_foreign_keys(copy_dsn, constraints)


def read_foreign_keys(dsn: str) -> list[dict[str, object]]:
    """Return foreign keys as JSON-ready objects, in a stable order."""
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows = connection.execute(_FK_QUERY).fetchall()
    constraints: list[dict[str, object]] = []
    for row in rows:
        constraints.append(
            {
                "schema": str(row["schema_name"]),
                "table": str(row["table_name"]),
                "name": str(row["constraint_name"]),
                "columns": [str(column) for column in cast(list[object], row["columns"])],
                "ref_schema": str(row["ref_schema"]),
                "ref_table": str(row["ref_table"]),
                "ref_columns": [str(column) for column in cast(list[object], row["ref_columns"])],
            }
        )
    return constraints


def drop_foreign_keys(dsn: str, constraints: list[dict[str, object]]) -> None:
    """Drop the named foreign keys."""
    with psycopg.connect(dsn, autocommit=True) as connection:
        for constraint in constraints:
            connection.execute(
                sql.SQL("ALTER TABLE {}.{} DROP CONSTRAINT {}").format(
                    sql.Identifier(str(constraint["schema"])),
                    sql.Identifier(str(constraint["table"])),
                    sql.Identifier(str(constraint["name"])),
                )
            )


def main() -> None:
    """Save Pagila foreign keys and drop them on ``<database>_nofk``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="Database to copy")
    parser.add_argument("--gold", required=True, type=Path, help="Path of the gold JSON file")
    args = parser.parse_args()
    prepare(args.dsn, args.gold)


if __name__ == "__main__":
    main()

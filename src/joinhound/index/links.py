# SPDX-License-Identifier: Apache-2.0

"""Read relationship rules stored in kg.links."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class ColumnLink:
    """One directed column relationship."""

    src_collection: str
    src_columns: tuple[str, ...]
    dst_collection: str
    dst_columns: tuple[str, ...]


def stored_links(dsn: str) -> list[ColumnLink]:
    """Return kg.links rows. A missing table is an empty ontology."""
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        present = connection.execute("SELECT to_regclass('kg.links') AS regclass").fetchone()
        if present is None or present["regclass"] is None:
            return []
        rows = connection.execute(
            """
            SELECT src_collection, src_column, dst_collection, dst_column
            FROM kg.links
            """
        ).fetchall()
    links: list[ColumnLink] = []
    for row in rows:
        dst_column = row["dst_column"]
        links.append(
            ColumnLink(
                src_collection=str(row["src_collection"]),
                src_columns=(str(row["src_column"]),),
                dst_collection=str(row["dst_collection"]),
                dst_columns=() if dst_column is None else (str(dst_column),),
            )
        )
    return links

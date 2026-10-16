# SPDX-License-Identifier: Apache-2.0

"""Read relationship rules stored in kg.links."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from joinhound.core.models import LinkDraft


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


def link_status(status: str, confidence: float, approve_at: float | None) -> str:
    """Promote a proposal when its confidence meets the auto-approve cutoff."""
    if status == "proposed" and approve_at is not None and confidence >= approve_at:
        return "approved"
    return status


def write_link(connection: psycopg.Connection, draft: LinkDraft, approve_at: float | None) -> None:
    """Insert one link. A proposed row may be updated; approved and rejected rows stay."""
    connection.execute(
        """
        INSERT INTO kg.links (
          link_id, src_collection, src_column, dst_collection, dst_column,
          match_type, origin, normalize_sql, threshold, confidence, cardinality,
          relation_name, status, evidence, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (link_id) DO UPDATE
        SET match_type = EXCLUDED.match_type,
            origin = EXCLUDED.origin,
            normalize_sql = EXCLUDED.normalize_sql,
            threshold = EXCLUDED.threshold,
            confidence = EXCLUDED.confidence,
            cardinality = EXCLUDED.cardinality,
            relation_name = EXCLUDED.relation_name,
            status = EXCLUDED.status,
            evidence = EXCLUDED.evidence,
            updated_at = now()
        WHERE kg.links.status = 'proposed'
        """,
        (
            draft.link_id,
            draft.src_collection,
            draft.src_column,
            draft.dst_collection,
            draft.dst_column,
            draft.match_type,
            draft.origin,
            draft.normalize_sql,
            draft.threshold,
            draft.confidence,
            draft.cardinality,
            draft.relation_name,
            link_status(draft.status, draft.confidence, approve_at),
            Json(draft.evidence),
        ),
    )


def save_links(dsn: str, drafts: list[LinkDraft], approve_at: float | None = None) -> None:
    """Insert relationships. Approved and rejected rows are left unchanged."""
    with psycopg.connect(dsn) as connection:
        for draft in drafts:
            write_link(connection, draft, approve_at)
        connection.commit()

# SPDX-License-Identifier: Apache-2.0

"""The Ossie document stored beside kg.links."""

from __future__ import annotations

from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from joinhound.core.models import EvidenceValue, LinkDraft
from joinhound.index.links import write_link

_SOURCE_ID = "ossie"


def store_model(dsn: str, text: str, drafts: list[LinkDraft]) -> None:
    """Replace the stored model and kg.links with one document."""
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO kg.sources (source_id, kind, config)
            VALUES (%s, 'ossie', %s)
            ON CONFLICT (source_id) DO UPDATE
            SET kind = 'ossie', config = EXCLUDED.config
            """,
            (_SOURCE_ID, Json({"text": text})),
        )
        connection.execute("DELETE FROM kg.links")
        for draft in drafts:
            write_link(connection, draft, None)
        connection.commit()


def model_text(dsn: str) -> str | None:
    """Return the Ossie document text last imported, if there is one."""
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            "SELECT config FROM kg.sources WHERE source_id = %s",
            (_SOURCE_ID,),
        ).fetchone()
    if row is None:
        return None
    config = cast(dict[str, Any], row["config"])
    text = config.get("text")
    return text if isinstance(text, str) else None


def model_links(dsn: str) -> list[LinkDraft]:
    """Return every stored link with the fields needed to rebuild a document."""
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT link_id, src_collection, src_column, dst_collection, dst_column,
                   match_type, origin, normalize_sql, threshold, confidence,
                   relation_name, cardinality, status, evidence
            FROM kg.links
            ORDER BY link_id
            """
        ).fetchall()
    return [_draft(cast(dict[str, Any], row)) for row in rows]


def _draft(row: dict[str, Any]) -> LinkDraft:
    evidence = row["evidence"] if isinstance(row["evidence"], dict) else {}
    return LinkDraft(
        link_id=str(row["link_id"]),
        src_collection=str(row["src_collection"]),
        src_column=str(row["src_column"]),
        dst_collection=str(row["dst_collection"]),
        dst_column=None if row["dst_column"] is None else str(row["dst_column"]),
        match_type=str(row["match_type"]),
        origin=str(row["origin"]),
        normalize_sql=None if row["normalize_sql"] is None else str(row["normalize_sql"]),
        threshold=None if row["threshold"] is None else float(row["threshold"]),
        confidence=float(row["confidence"]),
        relation_name=None if row["relation_name"] is None else str(row["relation_name"]),
        cardinality=None if row["cardinality"] is None else str(row["cardinality"]),
        status=str(row["status"]),
        evidence=cast(dict[str, EvidenceValue], evidence),
    )

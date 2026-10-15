# SPDX-License-Identifier: Apache-2.0

"""Write column fingerprints into kg.columns."""

from __future__ import annotations

import psycopg
from psycopg.types.json import Json

from joinhound.core.models import ColumnProfile


def save_column_profiles(dsn: str, source_id: str, profiles: list[ColumnProfile]) -> None:
    """Insert or replace column fingerprints. Parent source and collection rows are created."""
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO kg.sources (source_id, kind, config)
            VALUES (%s, 'postgres', %s)
            ON CONFLICT (source_id) DO NOTHING
            """,
            (source_id, Json({"type": "postgres"})),
        )
        for collection_id in sorted({profile.collection_id for profile in profiles}):
            connection.execute(
                """
                INSERT INTO kg.collections (collection_id, source_id, kind)
                VALUES (%s, %s, 'table')
                ON CONFLICT (collection_id) DO NOTHING
                """,
                (collection_id, source_id),
            )
        for profile in profiles:
            connection.execute(
                """
                INSERT INTO kg.columns (
                  collection_id, column_name, type_class, n_distinct, null_ratio,
                  uniqueness, pattern, minhash, profiled_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (collection_id, column_name) DO UPDATE
                SET type_class = EXCLUDED.type_class,
                    n_distinct = EXCLUDED.n_distinct,
                    null_ratio = EXCLUDED.null_ratio,
                    uniqueness = EXCLUDED.uniqueness,
                    pattern = EXCLUDED.pattern,
                    minhash = EXCLUDED.minhash,
                    profiled_at = now()
                """,
                (
                    profile.collection_id,
                    profile.column_name,
                    profile.type_class,
                    profile.n_distinct,
                    profile.null_ratio,
                    profile.uniqueness,
                    profile.pattern,
                    profile.minhash,
                ),
            )
        connection.commit()

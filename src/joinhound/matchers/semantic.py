# SPDX-License-Identifier: Apache-2.0

"""Relationships whose values are close in embedding space."""

from __future__ import annotations

import math

import psycopg
from psycopg.rows import dict_row

from joinhound.core.models import (
    Candidate,
    CollectionProfile,
    ColumnProfile,
    Link,
    Match,
    ProfileContext,
    QueryContext,
)
from joinhound.core.protocols import Embedder, TabularSource

_SAMPLE = 200
_COSINE = 0.8


class SemanticMatcher:
    """Propose a pair when sampled values point the same way, and resolve it with HNSW."""

    match_type = "semantic"

    def __init__(
        self,
        source: TabularSource,
        embedder: Embedder,
        index_dsn: str | None = None,
    ) -> None:
        self._source = source
        self._embedder = embedder
        self._index_dsn = index_dsn

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Count source values whose nearest destination value clears the cosine cutoff."""
        if not isinstance(dst, ColumnProfile):
            return None
        source_values = _distinct(self._source, src, min(_SAMPLE, ctx.sample_values))
        destination = _distinct(self._source, dst, min(_SAMPLE, ctx.sample_values))
        if len(source_values) < 2 or len(destination) < 2:
            return None
        source_vectors = self._embedder.embed(source_values)
        destination_vectors = self._embedder.embed(destination)
        hits = [
            value
            for value, vector in zip(source_values, source_vectors, strict=True)
            if _best(vector, destination_vectors) >= _COSINE
        ]
        fraction = len(hits) / len(source_values)
        if fraction < ctx.containment_threshold:
            return None
        return Candidate(
            match_type=self.match_type,
            confidence=fraction,
            evidence={"cosine": fraction, "matches": hits[:10]},
        )

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find destination rows near the query values."""
        if link.match_type != self.match_type or link.dst_column is None or ctx.limit <= 0:
            return []
        if not values:
            return []
        if self._index_dsn is not None:
            return _indexed(self._index_dsn, self._embedder, link, values, ctx.limit)
        return _sampled(self._source, self._embedder, link, values, ctx.limit)


def cosine(left: list[float], right: list[float]) -> float:
    """Return the cosine of two equal-length vectors."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _best(vector: list[float], others: list[list[float]]) -> float:
    return max(cosine(vector, other) for other in others)


def _sampled(
    source: TabularSource,
    embedder: Embedder,
    link: Link,
    values: list[str],
    limit: int,
) -> list[Match]:
    if link.dst_column is None:
        return []
    stored = list(source.scan_column(link.dst_collection, link.dst_column, None))
    if not stored:
        return []
    stored_vectors = embedder.embed([value for _pk, value in stored])
    query_vectors = embedder.embed(values)
    matches: list[Match] = []
    for value, vector in zip(values, query_vectors, strict=True):
        ranked = sorted(
            (
                (cosine(vector, stored_vector), pk)
                for (pk, _stored), stored_vector in zip(stored, stored_vectors, strict=True)
                if cosine(vector, stored_vector) >= _COSINE
            ),
            key=lambda item: (-item[0], str(item[1])),
        )
        for score, pk in ranked:
            matches.append(Match(pk=dict(pk), value=value, score=score))
            if len(matches) >= limit:
                return matches
    return matches


def _indexed(
    dsn: str,
    embedder: Embedder,
    link: Link,
    values: list[str],
    limit: int,
) -> list[Match]:
    if link.dst_column is None:
        return []
    vectors = embedder.embed(values)
    matches: list[Match] = []
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        for value, vector in zip(values, vectors, strict=True):
            literal = "[" + ",".join(f"{item:.6f}" for item in vector) + "]"
            rows = connection.execute(
                """
                SELECT pk, 1 - (embedding <=> %s::vector) AS score
                FROM kg.value_index
                WHERE collection_id = %s
                  AND column_name = %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (literal, link.dst_collection, link.dst_column, literal, limit),
            ).fetchall()
            for row in rows:
                score = float(row["score"])
                if score < _COSINE:
                    continue
                pk = row["pk"]
                if not isinstance(pk, dict):
                    continue
                matches.append(
                    Match(
                        pk={str(key): item for key, item in pk.items()},
                        value=value,
                        score=score,
                    )
                )
                if len(matches) >= limit:
                    return matches
    return matches


def _distinct(source: TabularSource, column: ColumnProfile, limit: int) -> list[str]:
    if limit <= 0:
        return []
    values: list[str] = []
    seen: set[str] = set()
    for row in source.sample(column.collection_id, [column.column_name], limit):
        raw = row.get(column.column_name)
        if raw is None:
            continue
        value = str(raw)
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values

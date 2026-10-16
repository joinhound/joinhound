# SPDX-License-Identifier: Apache-2.0

"""Relationships whose values are close but not equal after normalization."""

import psycopg
from psycopg.rows import dict_row
from rapidfuzz import fuzz

from joinhound.core.models import (
    Candidate,
    CollectionProfile,
    ColumnProfile,
    Link,
    Match,
    ProfileContext,
    QueryContext,
)
from joinhound.core.protocols import TabularSource
from joinhound.index.normalize import apply

_SAMPLE = 1000
_SIMILARITY = 0.6


class FuzzyMatcher:
    """Propose a text pair when enough sampled values are within the similarity threshold."""

    match_type = "fuzzy"

    def __init__(self, source: TabularSource, index_dsn: str | None = None) -> None:
        self._source = source
        self._index_dsn = index_dsn

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Score sampled pairs with rapidfuzz. Exact and normalized pairs are left alone."""
        if not isinstance(dst, ColumnProfile):
            return None
        if src.type_class != "text" or dst.type_class != "text":
            return None
        source_values = _distinct(self._source, src, min(_SAMPLE, ctx.sample_values))
        destination = _distinct(self._source, dst, min(_SAMPLE, ctx.sample_values))
        if not source_values or not destination:
            return None
        if _equal_after_fold(source_values, destination) >= ctx.containment_threshold:
            return None
        hits = [value for value in source_values if _best(value, destination) >= _SIMILARITY]
        fraction = len(hits) / len(source_values)
        if fraction < ctx.containment_threshold:
            return None
        return Candidate(
            match_type=self.match_type,
            confidence=fraction,
            evidence={"similarity": fraction, "matches": hits[:10]},
        )

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find close destination values. An index DSN uses pg_trgm; otherwise the sample."""
        if link.match_type != self.match_type or link.dst_column is None or ctx.limit <= 0:
            return []
        if self._index_dsn is not None:
            return _indexed(self._index_dsn, link, values, ctx.limit)
        return _sampled(self._source, link, values, ctx.limit)


def similarity(left: str, right: str) -> float:
    """Return rapidfuzz's normalized Indel similarity in the range 0 to 1."""
    return float(fuzz.ratio(apply("fold", left), apply("fold", right))) / 100


def _best(value: str, destination: list[str]) -> float:
    return max(similarity(value, other) for other in destination)


def _equal_after_fold(source_values: list[str], destination: list[str]) -> float:
    folded = {apply("fold", value) for value in destination}
    found = sum(apply("fold", value) in folded for value in source_values)
    return found / len(source_values)


def _sampled(
    source: TabularSource,
    link: Link,
    values: list[str],
    limit: int,
) -> list[Match]:
    if link.dst_column is None:
        return []
    stored = list(source.scan_column(link.dst_collection, link.dst_column, None))
    matches: list[Match] = []
    for value in values:
        ranked = sorted(
            (
                (similarity(value, stored_value), pk)
                for pk, stored_value in stored
                if similarity(value, stored_value) >= _SIMILARITY
            ),
            key=lambda item: (-item[0], str(item[1])),
        )
        for score, pk in ranked:
            matches.append(Match(pk=dict(pk), value=value, score=score))
            if len(matches) >= limit:
                return matches
    return matches


def _indexed(dsn: str, link: Link, values: list[str], limit: int) -> list[Match]:
    if link.dst_column is None:
        return []
    matches: list[Match] = []
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        for value in values:
            folded = apply("fold", value)
            rows = connection.execute(
                """
                SELECT pk, similarity(norm_value, %s) AS score
                FROM kg.value_index
                WHERE collection_id = %s
                  AND column_name = %s
                  AND norm_value %% %s
                  AND similarity(norm_value, %s) >= %s
                ORDER BY score DESC
                LIMIT %s
                """,
                (
                    folded,
                    link.dst_collection,
                    link.dst_column,
                    folded,
                    folded,
                    _SIMILARITY,
                    limit - len(matches),
                ),
            ).fetchall()
            for row in rows:
                pk = row["pk"]
                if not isinstance(pk, dict):
                    continue
                matches.append(
                    Match(
                        pk={str(key): item for key, item in pk.items()},
                        value=value,
                        score=float(row["score"]),
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

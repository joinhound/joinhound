# SPDX-License-Identifier: Apache-2.0

"""Relationships recovered by a closed set of normalization expressions."""

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
from joinhound.index.normalize import apply, names, sql_expression

_SAMPLE = 1000


class NormalizedMatcher:
    """Propose a pair when a library expression puts source values into the destination."""

    match_type = "normalized"

    def __init__(self, source: TabularSource) -> None:
        self._source = source

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Try each expression and keep the one with the highest containment."""
        if not isinstance(dst, ColumnProfile):
            return None
        source_values = _distinct(self._source, src, min(_SAMPLE, ctx.sample_values))
        destination = set(_distinct(self._source, dst, min(_SAMPLE, ctx.sample_values)))
        if not source_values or not destination:
            return None
        exact = _containment(source_values, destination, None)
        best_name = ""
        best = 0.0
        for name in names():
            score = _containment(source_values, destination, name)
            if score > best:
                best = score
                best_name = name
        if best < ctx.containment_threshold or best <= exact:
            return None
        return Candidate(
            match_type=self.match_type,
            confidence=best,
            evidence={"containment": best, "expression": best_name},
        )

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find destination rows equal to the values after the stored expression."""
        if link.match_type != self.match_type or link.dst_column is None or ctx.limit <= 0:
            return []
        expression = link.normalize_sql if link.normalize_sql in names() else "fold"
        if self._source.capabilities.pushdown_normalized:
            return _pushdown(self._source, link, values, expression, ctx.limit)
        return _local(self._source, link, values, expression, ctx.limit)


def _containment(source_values: list[str], destination: set[str], expression: str | None) -> float:
    if expression is None:
        found = sum(value in destination for value in source_values)
    else:
        folded = {apply(expression, value) for value in destination}
        found = sum(apply(expression, value) in folded for value in source_values)
    return found / len(source_values)


def _pushdown(
    source: TabularSource,
    link: Link,
    values: list[str],
    expression: str,
    limit: int,
) -> list[Match]:
    if link.dst_column is None:
        return []
    by_norm: dict[str, list[str]] = {}
    for value in values:
        by_norm.setdefault(apply(expression, value), []).append(value)
    found = source.find_values(
        link.dst_collection,
        link.dst_column,
        list(by_norm),
        "normalized",
        normalize_sql=sql_expression(expression, link.dst_column),
        limit=limit,
    )
    matches: list[Match] = []
    for match in found:
        for query_value in by_norm.get(apply(expression, match.value), []):
            matches.append(Match(pk=dict(match.pk), value=query_value, score=1.0))
            if len(matches) >= limit:
                return matches
    return matches


def _local(
    source: TabularSource,
    link: Link,
    values: list[str],
    expression: str,
    limit: int,
) -> list[Match]:
    if link.dst_column is None:
        return []
    stored = [
        (pk, apply(expression, value))
        for pk, value in source.scan_column(link.dst_collection, link.dst_column, None)
    ]
    matches: list[Match] = []
    for value in values:
        folded = apply(expression, value)
        for pk, destination in stored:
            if destination != folded:
                continue
            matches.append(Match(pk=dict(pk), value=value, score=1.0))
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

# SPDX-License-Identifier: Apache-2.0

"""Choose a value lookup from the deployment mode and source capabilities."""

from __future__ import annotations

from typing import Literal, cast

from joinhound.core.models import Match, Record
from joinhound.core.protocols import TabularSource
from joinhound.index.normalize import apply, names, sql_expression

Deployment = Literal["sidecar", "co_located"]


def direct_records(
    source: TabularSource,
    deployment: Deployment,
    collection_id: str,
    column: str,
    values: list[str],
    mode: Literal["exact", "normalized"],
    normalize_sql: str | None,
    limit: int,
) -> list[Record] | None:
    """Read matching rows in one statement when the service schema shares the source."""
    if deployment != "co_located" or not values:
        return None
    if mode == "exact" and not source.capabilities.pushdown_exact:
        return None
    if mode == "normalized" and not source.capabilities.pushdown_normalized:
        return None
    method = getattr(source, "match_records", None)
    if method is None:
        return None
    rows = method(collection_id, column, values, mode, normalize_sql, limit)
    if not isinstance(rows, list):
        return None
    return cast(list[Record], rows)


def normalized_matches(
    source: TabularSource,
    deployment: Deployment,
    collection_id: str,
    column: str,
    values: list[str],
    expression: str | None,
    limit: int,
) -> tuple[list[Match], list[Record]] | None:
    """Map query values onto rows already returned by one normalized statement."""
    name = expression if expression in names() else "fold"
    by_norm: dict[str, list[str]] = {}
    for value in values:
        by_norm.setdefault(apply(name, value), []).append(value)
    rows = direct_records(
        source,
        deployment,
        collection_id,
        column,
        list(by_norm),
        "normalized",
        sql_expression(name, column),
        limit,
    )
    if rows is None:
        return None
    matches: list[Match] = []
    for row in rows:
        raw = row.values.get(column)
        cell = "" if raw is None else str(raw)
        for query_value in by_norm.get(apply(name, cell), []):
            matches.append(Match(pk=dict(row.pk), value=query_value, score=1.0))
            if len(matches) >= limit:
                return matches, rows
    return matches, rows

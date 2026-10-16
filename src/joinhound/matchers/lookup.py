# SPDX-License-Identifier: Apache-2.0

"""Destination lookup shared by equality matchers."""

from joinhound.core.models import Link, Match, QueryContext
from joinhound.core.protocols import TabularSource


def lookup_destination(
    source: TabularSource,
    link: Link,
    values: list[str],
    ctx: QueryContext,
) -> list[Match]:
    """Find destination rows equal to the given values. Matches score 1.0."""
    if link.dst_column is None or not values or ctx.limit <= 0:
        return []
    found = source.find_values(
        link.dst_collection,
        link.dst_column,
        values,
        "exact",
        limit=ctx.limit,
    )
    return [Match(pk=dict(match.pk), value=match.value, score=1.0) for match in found]

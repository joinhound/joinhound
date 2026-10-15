# SPDX-License-Identifier: Apache-2.0

"""Relationships whose sampled values are contained by equality."""

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
from joinhound.matchers.lookup import lookup_destination

_EXACT_SAMPLE = 1000


class ExactMatcher:
    """Propose a pair when sampled source values are contained in the destination."""

    match_type = "exact"

    def __init__(self, source: TabularSource) -> None:
        self._source = source

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Return the pair when distinct-value containment meets the threshold."""
        if not isinstance(dst, ColumnProfile):
            return None
        values = _distinct_sample(self._source, src, min(_EXACT_SAMPLE, ctx.sample_values))
        if not values:
            return None
        matches = self._source.find_values(
            dst.collection_id,
            dst.column_name,
            values,
            "exact",
            limit=len(values),
        )
        found = {match.value for match in matches}
        containment = len(found & set(values)) / len(values)
        if containment < ctx.containment_threshold:
            return None
        return Candidate(match_type=self.match_type, confidence=containment)

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find destination rows equal to the given values."""
        if link.match_type != self.match_type:
            return []
        return lookup_destination(self._source, link, values, ctx)


def _distinct_sample(source: TabularSource, column: ColumnProfile, limit: int) -> list[str]:
    if limit <= 0:
        return []
    rows = source.sample(column.collection_id, [column.column_name], limit)
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw = row.get(column.column_name)
        if raw is None:
            continue
        value = str(raw)
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values

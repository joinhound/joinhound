# SPDX-License-Identifier: Apache-2.0

"""Relationships taken from foreign keys declared by the source."""

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


class DeclaredFkMatcher:
    """Approve a single-column foreign key and resolve it by equality."""

    match_type = "declared_fk"

    def __init__(self, source: TabularSource) -> None:
        self._source = source

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Return the declared foreign key when this pair is exactly that key."""
        del ctx
        if not isinstance(dst, ColumnProfile):
            return None
        for link in self._source.declared_links():
            if (
                link.src_collection == src.collection_id
                and link.dst_collection == dst.collection_id
                and link.src_columns == [src.column_name]
                and link.dst_columns == [dst.column_name]
            ):
                return Candidate(
                    match_type=self.match_type,
                    confidence=1.0,
                    evidence={"catalog": True},
                )
        return None

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find destination rows whose key equals one of the foreign-key values."""
        if link.match_type != self.match_type:
            return []
        return lookup_destination(self._source, link, values, ctx)

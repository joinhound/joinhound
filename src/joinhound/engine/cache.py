# SPDX-License-Identifier: Apache-2.0

"""Short-lived cache of get_context results. Record pairs are not stored."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.engine.lookup import Deployment
from joinhound.engine.response import ContextResponse


@dataclass
class ResultCache:
    """Keep a response until its TTL elapses. A non-positive TTL stores nothing."""

    ttl_seconds: float
    _stored: dict[str, tuple[float, ContextResponse]] = field(default_factory=dict)

    def get(self, key: str, now: float) -> ContextResponse | None:
        """Return a copy of a fresh response, or nothing when the entry expired."""
        item = self._stored.get(key)
        if item is None:
            return None
        stored_at, value = item
        if self.ttl_seconds <= 0 or now - stored_at >= self.ttl_seconds:
            del self._stored[key]
            return None
        return value.model_copy(deep=True)

    def put(self, key: str, value: ContextResponse, now: float) -> None:
        """Store a copy of a response. A non-positive TTL drops it."""
        if self.ttl_seconds <= 0:
            return
        self._stored[key] = (now, value.model_copy(deep=True))


def cache_key(
    query: str,
    *,
    budget: int,
    depth: int,
    scope: Sequence[str] | None,
    deployment: Deployment,
    links: Sequence[LinkDraft],
    roles: Sequence[str] | None,
    passages: Sequence[IndexedPassage],
) -> str:
    """Identify one get_context call. The key expires with the cache entry."""
    payload = {
        "query": query,
        "budget": budget,
        "depth": depth,
        "scope": list(scope or []),
        "deployment": deployment,
        "roles": list(roles or []),
        "links": [
            (
                link.link_id,
                link.status,
                link.match_type,
                link.src_collection,
                link.src_column,
                link.dst_collection,
                link.dst_column,
                link.confidence,
            )
            for link in links
        ],
        "passages": [(passage.uri, passage.text) for passage in passages],
    }
    return json.dumps(payload, sort_keys=True, default=str)

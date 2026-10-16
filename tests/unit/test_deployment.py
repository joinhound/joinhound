# SPDX-License-Identifier: Apache-2.0

"""co_located reads an exact match in one statement; sidecar searches and then fetches."""

from __future__ import annotations

from typing import Literal

from joinhound.core.config import EngineConfig
from joinhound.core.models import DeclaredFK, LinkDraft, Match, Record
from joinhound.engine.context import get_context
from joinhound.engine.lookup import Deployment
from joinhound.engine.response import ContextResponse
from joinhound.matchers import DeclaredFkMatcher
from joinhound.profiler.profile import link_id
from joinhound.testing.memory import MemoryTabularSource


def test_both_modes_return_the_same_rows_and_co_located_skips_the_second_read() -> None:
    sidecar = _Counting()
    colocated = _Counting()
    sidecar_graph = _walk(sidecar, "sidecar")
    colocated_graph = _walk(colocated, "co_located")

    assert {node.uri for node in sidecar_graph.nodes} == {
        node.uri for node in colocated_graph.nodes
    }
    assert "match" not in sidecar.calls
    assert "find" in sidecar.calls
    assert "fetch" in sidecar.calls
    assert "match" in colocated.calls
    assert "find" not in colocated.calls
    assert "fetch" not in colocated.calls


def _walk(source: _Counting, deployment: Deployment) -> ContextResponse:
    return get_context(
        "ACADEMY DINOSAUR",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=10, budget_tokens=100_000),
        max_depth=1,
        clock=lambda: 0.0,
        deployment=deployment,
    )


class _Counting(MemoryTabularSource):
    def __init__(self) -> None:
        super().__init__(
            {
                "films": [{"id": 1, "title": "ACADEMY DINOSAUR"}],
                "cast": [{"id": 100, "film_id": 1, "actor_id": 10}],
            },
            [
                DeclaredFK(
                    src_collection="cast",
                    src_columns=["film_id"],
                    dst_collection="films",
                    dst_columns=["id"],
                )
            ],
        )
        self.calls: list[str] = []

    def match_records(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: Literal["exact", "normalized"],
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Record]:
        self.calls.append("match")
        found = MemoryTabularSource.find_values(
            self, coll, column, values, mode, normalize_sql, limit
        )
        return MemoryTabularSource.fetch_by_keys(self, coll, [dict(match.pk) for match in found])

    def find_values(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: str,
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        self.calls.append("find")
        return super().find_values(coll, column, values, mode, normalize_sql, limit)

    def fetch_by_keys(self, coll: str, keys: list[dict[str, object]]) -> list[Record]:
        self.calls.append("fetch")
        return super().fetch_by_keys(coll, keys)


def _links() -> list[LinkDraft]:
    return [
        LinkDraft(
            link_id=link_id("cast", "film_id", "films", "id"),
            src_collection="cast",
            src_column="film_id",
            dst_collection="films",
            dst_column="id",
            match_type="declared_fk",
            origin="catalog_fk",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        )
    ]

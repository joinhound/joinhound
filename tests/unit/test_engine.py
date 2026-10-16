# SPDX-License-Identifier: Apache-2.0

"""Beam search, scores, fanout, and the token budget."""

import pytest

from joinhound.core.config import EngineConfig
from joinhound.core.models import DeclaredFK, LinkDraft
from joinhound.engine.context import get_context
from joinhound.engine.response import ContextNode, ContextResponse
from joinhound.engine.score import path_score, relevance
from joinhound.matchers import DeclaredFkMatcher
from joinhound.profiler.profile import link_id
from joinhound.testing.memory import MemoryTabularSource


def _frozen() -> float:
    return 0.0


def test_path_score_decays_with_depth_and_keeps_a_floor() -> None:
    assert relevance("ACADEMY DINOSAUR", "ACADEMY DINOSAUR") == pytest.approx(1.0)
    assert relevance("ACADEMY DINOSAUR", "") == pytest.approx(0.3)
    assert path_score(1.0, (), 0.8) == 1.0
    assert path_score(1.0, (1.0, 1.0), 0.8) == pytest.approx(0.64)


def test_fanout_limits_neighbors_of_one_link() -> None:
    source = _source()
    narrow = get_context(
        "ACADEMY DINOSAUR",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=1, budget_tokens=100_000),
        max_depth=1,
        clock=_frozen,
    )
    wide = get_context(
        "ACADEMY DINOSAUR",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=10, budget_tokens=100_000),
        max_depth=1,
        clock=_frozen,
    )

    assert len(_casts(narrow)) == 1
    assert len(_casts(wide)) == 3
    assert narrow.stats.tokens <= 100_000
    assert {edge.from_ for edge in narrow.edges} <= {node.id for node in narrow.nodes}
    assert {edge.to for edge in narrow.edges} <= {node.id for node in narrow.nodes}


def test_budget_stops_before_the_next_node() -> None:
    source = _source()
    settings = EngineConfig(fanout=10, budget_tokens=100_000)
    matchers = {"declared_fk": DeclaredFkMatcher(source)}
    seeds = get_context(
        "ACADEMY DINOSAUR",
        source,
        _links(),
        matchers,
        settings,
        max_depth=0,
        clock=_frozen,
    )
    limited = get_context(
        "ACADEMY DINOSAUR",
        source,
        _links(),
        matchers,
        settings,
        budget_tokens=seeds.stats.tokens,
        max_depth=1,
        clock=_frozen,
    )

    assert limited.stats.tokens <= seeds.stats.tokens
    assert limited.truncated
    assert [node.uri for node in limited.nodes] == [node.uri for node in seeds.nodes]
    assert limited.expandable


def test_timeout_returns_seeds_and_marks_the_answer_truncated() -> None:
    source = _source()
    result = get_context(
        "ACADEMY DINOSAUR",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(timeout_ms=0, fanout=10, budget_tokens=100_000),
        max_depth=2,
        clock=_frozen,
    )

    assert result.truncated
    assert result.nodes
    assert all(node.seed for node in result.nodes)


def test_two_walks_return_the_same_graph() -> None:
    source = _source()
    settings = EngineConfig(fanout=10, budget_tokens=100_000)
    matchers = {"declared_fk": DeclaredFkMatcher(source)}
    first = get_context("ACADEMY DINOSAUR", source, _links(), matchers, settings, clock=_frozen)
    second = get_context("ACADEMY DINOSAUR", source, _links(), matchers, settings, clock=_frozen)

    assert first.model_dump(by_alias=True) == second.model_dump(by_alias=True)
    assert "from" in first.model_dump(by_alias=True)["edges"][0]


def _casts(result: ContextResponse) -> list[ContextNode]:
    return [node for node in result.nodes if node.collection == "cast"]


def _source() -> MemoryTabularSource:
    return MemoryTabularSource(
        {
            "films": [{"id": 1, "title": "ACADEMY DINOSAUR"}],
            "cast": [
                {"id": 100, "film_id": 1, "actor_id": 10, "note": "one"},
                {"id": 101, "film_id": 1, "actor_id": 11, "note": "two"},
                {"id": 102, "film_id": 1, "actor_id": 12, "note": "WORD " * 40},
            ],
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

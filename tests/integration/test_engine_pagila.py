# SPDX-License-Identifier: Apache-2.0

"""get_context walks Pagila from a title mentioned in the query."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import EngineConfig, PostgresSourceConfig
from joinhound.core.models import LinkDraft
from joinhound.engine.context import get_context
from joinhound.engine.dictionary import build_dictionary
from joinhound.engine.response import ContextNode, ContextResponse
from joinhound.matchers import DeclaredFkMatcher
from joinhound.profiler.profile import link_id

_PAGILA_REF = "ce6e114236bb828e5ec0dc835f65f1bf1b9179f5"
_ROOT = Path(__file__).resolve().parents[2]


def _frozen() -> float:
    return 0.0


@pytest.fixture(scope="module")
def pagila_dsn() -> Iterator[str]:
    with PostgresContainer(
        "pgvector/pgvector:pg18",
        username="postgres",
        password="postgres",
        dbname="pagila",
        driver=None,
    ) as postgres:
        _load_pagila(postgres)
        yield postgres.get_connection_url(driver=None)


def test_title_seed_respects_fanout_and_budget(pagila_dsn: str) -> None:
    with PostgresSource(
        "pagila",
        PostgresSourceConfig(
            type="postgres",
            dsn=pagila_dsn,
            schemas=["public"],
            statement_timeout_ms=30_000,
        ),
    ) as source:
        links = _declared(source)
        dictionary = build_dictionary(source, links)
        matchers = {"declared_fk": DeclaredFkMatcher(source)}
        settings = EngineConfig(fanout=25, budget_tokens=8000)
        first = get_context(
            "ACADEMY DINOSAUR",
            source,
            links,
            matchers,
            settings,
            max_depth=1,
            dictionary=dictionary,
            clock=_frozen,
        )
        second = get_context(
            "ACADEMY DINOSAUR",
            source,
            links,
            matchers,
            settings,
            max_depth=1,
            dictionary=dictionary,
            clock=_frozen,
        )
        narrow = get_context(
            "ACADEMY DINOSAUR",
            source,
            links,
            matchers,
            EngineConfig(fanout=1, budget_tokens=8000),
            max_depth=1,
            dictionary=dictionary,
            clock=_frozen,
        )
        seeds = get_context(
            "ACADEMY DINOSAUR",
            source,
            links,
            matchers,
            settings,
            max_depth=0,
            dictionary=dictionary,
            clock=_frozen,
        )
        limited = get_context(
            "ACADEMY DINOSAUR",
            source,
            links,
            matchers,
            settings,
            budget_tokens=seeds.stats.tokens,
            max_depth=1,
            dictionary=dictionary,
            clock=_frozen,
        )

    assert first.model_dump() == second.model_dump()
    film = _film(first)
    assert film.seed
    assert film.content["title"] == "ACADEMY DINOSAUR"
    assert _neighbor_count(first) > _neighbor_count(narrow)
    assert _neighbor_count(narrow) <= _link_count(first)
    assert first.stats.tokens <= 8000
    assert limited.stats.tokens <= seeds.stats.tokens
    assert limited.truncated
    assert len(limited.nodes) < len(first.nodes)
    ids = {node.id for node in first.nodes}
    assert {edge.from_ for edge in first.edges} <= ids
    assert {edge.to for edge in first.edges} <= ids


def _film(result: ContextResponse) -> ContextNode:
    matches = [
        node
        for node in result.nodes
        if node.collection.endswith("public.film")
        and node.content.get("title") == "ACADEMY DINOSAUR"
    ]
    assert len(matches) == 1
    return matches[0]


def _neighbor_count(result: ContextResponse) -> int:
    return sum(1 for node in result.nodes if not node.seed)


def _link_count(result: ContextResponse) -> int:
    return len({edge.link_id for edge in result.edges}) or 1


def _declared(source: PostgresSource) -> list[LinkDraft]:
    drafts: list[LinkDraft] = []
    for foreign_key in source.declared_links():
        if len(foreign_key.src_columns) != 1 or len(foreign_key.dst_columns) != 1:
            continue
        src_column = foreign_key.src_columns[0]
        dst_column = foreign_key.dst_columns[0]
        drafts.append(
            LinkDraft(
                link_id=link_id(
                    foreign_key.src_collection,
                    src_column,
                    foreign_key.dst_collection,
                    dst_column,
                ),
                src_collection=foreign_key.src_collection,
                src_column=src_column,
                dst_collection=foreign_key.dst_collection,
                dst_column=dst_column,
                match_type="declared_fk",
                origin="catalog_fk",
                confidence=1.0,
                status="approved",
                cardinality="N:1",
            )
        )
    return drafts


def _load_pagila(postgres: PostgresContainer) -> None:
    container_id = postgres.get_wrapped_container().id
    for name in ("pagila-schema.sql", "pagila-data.sql"):
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container_id,
                "psql",
                "--username",
                "postgres",
                "--dbname",
                "pagila",
                "--set",
                "ON_ERROR_STOP=1",
            ],
            input=_pagila_file(name).read_bytes(),
            check=True,
        )


def _pagila_file(name: str) -> Path:
    cache = _ROOT / "cache" / "pagila" / _PAGILA_REF
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    if path.is_file() and path.stat().st_size > 0:
        return path
    url = f"https://raw.githubusercontent.com/devrimgunduz/pagila/{_PAGILA_REF}/{name}"
    subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location", "--output", str(path), url],
        check=True,
    )
    return path

# SPDX-License-Identifier: Apache-2.0

"""A step sends every value in one query, and a fresh result is reused until its TTL."""

import math
import time

from joinhound.core.config import EngineConfig
from joinhound.core.models import IndexedPassage, Match, Record
from joinhound.core.uri import S3Uri, build_uri
from joinhound.engine.cache import ResultCache
from joinhound.engine.context import get_context
from joinhound.engine.dictionary import ValueDictionary
from joinhound.testing.memory import MemoryTabularSource

_DOCUMENTS = 1000


def test_one_step_sends_every_mentioned_value_in_one_query() -> None:
    source = _Films()
    get_context(
        "ONE TWO THREE",
        source,
        [],
        {},
        EngineConfig(),
        max_depth=0,
        dictionary=_titles(),
        clock=lambda: 0.0,
    )

    assert source.values == [["ONE", "THREE", "TWO"]]


def test_get_context_reuses_a_response_until_the_ttl() -> None:
    source = _Films()
    cache = ResultCache(ttl_seconds=30)
    clock = _Clock()
    settings = EngineConfig(cache_ttl_seconds=30)

    def ask() -> None:
        get_context(
            "ONE",
            source,
            [],
            {},
            settings,
            max_depth=0,
            dictionary=_titles(),
            clock=clock,
            cache=cache,
        )

    ask()
    clock.now = 10
    ask()
    assert len(source.values) == 1
    clock.now = 30
    ask()
    assert len(source.values) == 2


def test_thousand_passages_stay_under_two_seconds() -> None:
    passages = [
        IndexedPassage(
            uri=build_uri(S3Uri("corpus", f"doc-{index}.txt")),
            collection_id="s3://corpus/",
            text=f"document {index}",
            page=1,
            bbox=(0.0, 0.0, 1.0, 1.0),
        )
        for index in range(_DOCUMENTS)
    ]
    passages[-1] = passages[-1].model_copy(update={"text": "UNIQUE-CODE-1000"})
    source = _Films()
    seen: list[int] = []

    def ask() -> None:
        result = get_context(
            "UNIQUE-CODE-1000",
            source,
            [],
            {},
            EngineConfig(timeout_ms=2000),
            max_depth=0,
            dictionary=ValueDictionary(),
            passages=passages,
            clock=lambda: 0.0,
        )
        seen.append(len(result.nodes))

    samples = [_seconds(ask) for _ in range(20)]

    assert seen[-1] >= 1
    assert _p95(samples) < 2


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Films(MemoryTabularSource):
    def __init__(self) -> None:
        super().__init__(
            {
                "films": [
                    {"id": 1, "title": "ONE"},
                    {"id": 2, "title": "TWO"},
                    {"id": 3, "title": "THREE"},
                ]
            }
        )
        self.values: list[list[str]] = []

    def find_values(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: str,
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        self.values.append(sorted(values))
        return super().find_values(coll, column, values, mode, normalize_sql, limit)

    def fetch_by_keys(self, coll: str, keys: list[dict[str, object]]) -> list[Record]:
        return super().fetch_by_keys(coll, keys)


def _titles() -> ValueDictionary:
    dictionary = ValueDictionary()
    for title in ("ONE", "TWO", "THREE"):
        dictionary.add("films", "title", title)
    dictionary.freeze()
    return dictionary


def _seconds(call: object) -> float:
    started = time.perf_counter()
    if not callable(call):
        raise AssertionError("timer target must be callable")
    call()
    return time.perf_counter() - started


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]

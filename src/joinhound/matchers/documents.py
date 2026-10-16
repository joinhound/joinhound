# SPDX-License-Identifier: Apache-2.0

"""Relationships between a column and a document collection."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import ahocorasick  # type: ignore[import-not-found]

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

_DISCOVER_VALUES = 200
_MIN_FRACTION = 0.3
_MAX_FREQUENCY = 0.5
_TRIGRAM = 0.6


@dataclass(frozen=True)
class Passage:
    """One indexed fragment the matcher can search."""

    collection_id: str
    pk: dict[str, object]
    text: str


class DocumentMatcher:
    """Propose a column when its values are rare phrases in a document collection."""

    match_type = "column_documents"

    def __init__(self, source: TabularSource, passages: Sequence[Passage] = ()) -> None:
        self._source = source
        self._passages = list(passages)

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Return a candidate when enough sampled values are rare phrases in the collection."""
        if not isinstance(dst, CollectionProfile):
            return None
        values = _distinct_sample(self._source, src, min(_DISCOVER_VALUES, ctx.sample_values))
        passages = _in_collection(self._passages, dst.collection_id)
        if not values or not passages:
            return None
        distinctive: list[str] = []
        idf_total = 0.0
        for value in values:
            hits = _phrase_hits(passages, value)
            if not _rare(len(hits), len(passages)):
                continue
            distinctive.append(value)
            idf_total += math.log((len(passages) + 1) / (len(hits) + 1))
        fraction = len(distinctive) / len(values)
        if fraction < _MIN_FRACTION:
            return None
        missed = [value for value in values if value not in set(distinctive)]
        return Candidate(
            match_type=self.match_type,
            confidence=fraction,
            evidence={
                "containment": fraction,
                "idf": idf_total / len(distinctive),
                "matches": distinctive[:10],
                "misses": missed[:5],
            },
        )

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find fragments that contain the values as a phrase, then by trigram similarity."""
        if link.match_type != self.match_type or link.dst_column is not None:
            return []
        if not values or ctx.limit <= 0:
            return []
        passages = _in_collection(self._passages, link.dst_collection)
        found: list[Match] = []
        for value in values:
            hits = [(passage, 1.0) for passage in _phrase_hits(passages, value)]
            if not hits:
                hits = _trigram_hits(passages, value)
            for passage, score in hits:
                found.append(Match(pk=dict(passage.pk), value=value, score=score))
                if len(found) >= ctx.limit:
                    return found
        return found

    def mentions(self, link: Link, passage: str, ctx: QueryContext) -> list[Match]:
        """Find rows whose column value occurs in a fragment."""
        if link.match_type != self.match_type or ctx.limit <= 0 or not passage:
            return []
        values = _column_values(self._source, link.src_collection, link.src_column)
        hits = _automaton_hits(values, passage)
        if not hits:
            return []
        found = self._source.find_values(
            link.src_collection,
            link.src_column,
            hits,
            "exact",
            limit=ctx.limit,
        )
        return [Match(pk=dict(match.pk), value=match.value, score=1.0) for match in found]


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


def _column_values(source: TabularSource, collection_id: str, column: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for _pk, value in source.scan_column(collection_id, column, None):
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _in_collection(passages: Sequence[Passage], collection_id: str) -> list[Passage]:
    return [passage for passage in passages if passage.collection_id == collection_id]


def _rare(hits: int, total: int) -> bool:
    if hits <= 0:
        return False
    if total < 2:
        return True
    return hits / total <= _MAX_FREQUENCY


def _phrase_hits(passages: Sequence[Passage], value: str) -> list[Passage]:
    return [passage for passage in passages if _contains_phrase(passage.text, value)]


def _contains_phrase(text: str, value: str) -> bool:
    if not value:
        return False
    haystack = text.casefold()
    needle = value.casefold()
    start = haystack.find(needle)
    while start >= 0:
        if _bounded(haystack, start, start + len(needle) - 1):
            return True
        start = haystack.find(needle, start + 1)
    return False


def _trigram_hits(passages: Sequence[Passage], value: str) -> list[tuple[Passage, float]]:
    scored = [(passage, _word_similarity(value, passage.text)) for passage in passages]
    return [(passage, score) for passage, score in scored if score >= _TRIGRAM]


def _word_similarity(needle: str, haystack: str) -> float:
    needle_grams = _trigrams(needle.casefold())
    if not needle_grams:
        return 0.0
    best = 0.0
    for word in haystack.casefold().split():
        grams = _trigrams(word)
        if not grams:
            continue
        score = len(needle_grams & grams) / len(needle_grams | grams)
        if score > best:
            best = score
    return best


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def _automaton_hits(values: Sequence[str], passage: str) -> list[str]:
    automaton: Any = ahocorasick.Automaton()
    stored = [value for value in values if value]
    if not stored:
        return []
    for value in stored:
        automaton.add_word(value.casefold(), value)
    automaton.make_automaton()
    haystack = passage.casefold()
    found: list[str] = []
    seen: set[str] = set()
    for end, raw in cast(Any, automaton.iter(haystack)):
        value = str(raw)
        start = end - len(value) + 1
        if value in seen or not _bounded(haystack, start, end):
            continue
        seen.add(value)
        found.append(value)
    return found


def _bounded(text: str, start: int, end: int) -> bool:
    before = start > 0 and text[start - 1].isalnum()
    after = end + 1 < len(text) and text[end + 1].isalnum()
    return not before and not after

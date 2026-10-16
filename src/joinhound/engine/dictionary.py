# SPDX-License-Identifier: Apache-2.0

"""Dictionary of column values used to find mentions in a query."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

import ahocorasick  # type: ignore[import-not-found]

from joinhound.core.models import LinkDraft
from joinhound.core.protocols import TabularSource

_MIN_LENGTH = 3
_MAX_LENGTH = 80


@dataclass(frozen=True)
class Mention:
    """A dictionary value found inside the query text."""

    value: str
    start: int
    collection_id: str
    column: str


class ValueDictionary:
    """Aho-Corasick automaton over values that a query may mention."""

    def __init__(self) -> None:
        self._locations: dict[str, list[tuple[str, str]]] = {}
        self._automaton: Any = None

    def add(self, collection_id: str, column: str, value: str) -> None:
        """Remember one column value. Short, blank, and very long values are ignored."""
        if not _kept(value):
            return
        places = self._locations.setdefault(value, [])
        pair = (collection_id, column)
        if pair not in places:
            places.append(pair)

    def freeze(self) -> None:
        """Build the automaton. Further additions are ignored by search."""
        if not self._locations:
            return
        automaton: Any = ahocorasick.Automaton()
        for value in self._locations:
            automaton.add_word(value, value)
        automaton.make_automaton()
        self._automaton = automaton

    def mentions(self, query: str) -> list[Mention]:
        """Return token-bounded mentions, longest first."""
        automaton = self._automaton
        if automaton is None or not query:
            return []
        found: list[Mention] = []
        for end, raw in cast(Iterator[tuple[int, object]], automaton.iter(query)):
            value = str(raw)
            start = end - len(value) + 1
            if start < 0 or not _bounded(query, start, end):
                continue
            for collection_id, column in self._locations.get(value, []):
                found.append(
                    Mention(
                        value=value,
                        start=start,
                        collection_id=collection_id,
                        column=column,
                    )
                )
        found.sort(key=lambda item: (-len(item.value), item.start, item.collection_id, item.column))
        return found


def build_dictionary(source: TabularSource, links: Sequence[LinkDraft]) -> ValueDictionary:
    """Index text columns, and the columns named by approved links, from the source."""
    dictionary = ValueDictionary()
    for collection_id, columns in _columns(source, links).items():
        for column in columns:
            for _pk, value in source.scan_column(collection_id, column, None):
                dictionary.add(collection_id, column, value)
    dictionary.freeze()
    return dictionary


def _columns(source: TabularSource, links: Sequence[LinkDraft]) -> dict[str, list[str]]:
    named: set[tuple[str, str]] = set()
    collections: set[str] = set()
    for link in links:
        if link.status != "approved":
            continue
        if link.dst_column is None:
            if link.match_type == "column_documents":
                collections.add(link.src_collection)
                named.add((link.src_collection, link.src_column))
            continue
        collections.add(link.src_collection)
        collections.add(link.dst_collection)
        named.add((link.src_collection, link.src_column))
        named.add((link.dst_collection, link.dst_column))
    selected = set(named)
    for collection_id in sorted(collections):
        for stat in source.column_stats(collection_id):
            if stat.type_class == "text":
                selected.add((collection_id, stat.column_name))
    grouped: dict[str, list[str]] = {}
    for collection_id, column in sorted(selected):
        grouped.setdefault(collection_id, []).append(column)
    return grouped


def _kept(value: str) -> bool:
    return _MIN_LENGTH <= len(value) <= _MAX_LENGTH and not value.isspace()


def _bounded(query: str, start: int, end: int) -> bool:
    before = start > 0 and query[start - 1].isalnum()
    after = end + 1 < len(query) and query[end + 1].isalnum()
    return not before and not after

# SPDX-License-Identifier: Apache-2.0

"""Lexical and semantic passage seeds, fused with reciprocal rank."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

from joinhound.core.models import IndexedPassage

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_RRF_K = 60


def visible_passages(
    passages: Sequence[IndexedPassage],
    roles: Sequence[str] | None,
) -> list[IndexedPassage]:
    """Drop fragments the caller is not allowed to read."""
    allowed = set(roles or ())
    return [passage for passage in passages if _visible(passage.roles, allowed)]


def lexical_rank(query: str, passages: Sequence[IndexedPassage]) -> list[str]:
    """Rank fragments in which every query word occurs, most repetitions first."""
    tokens = [token.casefold() for token in _TOKEN.findall(query)]
    if not tokens:
        return []
    scored: list[tuple[int, str]] = []
    for passage in passages:
        text = passage.text.casefold()
        if not all(_contains_word(text, token) for token in tokens):
            continue
        scored.append((sum(text.count(token) for token in tokens), passage.uri))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return _unique(uri for _count, uri in scored)


def semantic_rank(vector: Sequence[float], passages: Sequence[IndexedPassage]) -> list[str]:
    """Rank fragments by cosine similarity to the query embedding."""
    scored: list[tuple[float, str]] = []
    for passage in passages:
        if passage.embedding is None:
            continue
        score = _cosine(vector, passage.embedding)
        if score <= 0:
            continue
        scored.append((score, passage.uri))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return _unique(uri for _score, uri in scored)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]]) -> list[str]:
    """Fuse ranked lists. A document at rank r adds 1 / (60 + r)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, uri in enumerate(ranking, start=1):
            scores[uri] = scores.get(uri, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(scores, key=lambda uri: (-scores[uri], uri))


def _visible(roles: Sequence[str], allowed: set[str]) -> bool:
    if not roles:
        return True
    return bool(set(roles) & allowed)


def _contains_word(text: str, token: str) -> bool:
    start = text.find(token)
    while start >= 0:
        end = start + len(token) - 1
        before = start > 0 and text[start - 1].isalnum()
        after = end + 1 < len(text) and text[end + 1].isalnum()
        if not before and not after:
            return True
        start = text.find(token, start + 1)
    return False


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _unique(uris: Iterable[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for uri in uris:
        if uri in seen:
            continue
        seen.add(uri)
        found.append(uri)
    return found

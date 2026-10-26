# SPDX-License-Identifier: Apache-2.0

"""Lexical and semantic passage seeds, fused with reciprocal rank."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

from joinhound.core.models import IndexedPassage

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_SENTENCE = re.compile(r"[^.!?\n]+")
_RRF_K = 60
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "which",
        "who",
        "with",
    }
)


def visible_passages(
    passages: Sequence[IndexedPassage],
    roles: Sequence[str] | None,
) -> list[IndexedPassage]:
    """Drop fragments the caller is not allowed to read."""
    allowed = set(roles or ())
    return [passage for passage in passages if _visible(passage.roles, allowed)]


def lexical_rank(query: str, passages: Sequence[IndexedPassage]) -> list[str]:
    """Rank the note that puts the most rare query words in one sentence."""
    tokens = [token.casefold() for token in _TOKEN.findall(query)]
    content = list(
        dict.fromkeys(token for token in tokens if token not in _STOP and len(token) >= 3)
    )
    if not content:
        content = list(dict.fromkeys(tokens))
    if not content or not passages:
        return []
    wanted = set(content)
    located: list[tuple[str, list[set[str]]]] = []
    document_frequency = dict.fromkeys(content, 0)
    for passage in passages:
        sentences = [
            set(_TOKEN.findall(part)) for part in _SENTENCE.findall(passage.text.casefold())
        ]
        present = set().union(*sentences) if sentences else set()
        matched = present & wanted
        if not matched:
            continue
        for token in matched:
            document_frequency[token] += 1
        located.append((passage.uri, sentences))
    if not located:
        return []
    total = len(passages)
    rare = {token for token, count in document_frequency.items() if count and count / total <= 0.1}
    focus = rare or {token for token, count in document_frequency.items() if count}
    scored: list[tuple[int, int, str]] = []
    for uri, sentences in located:
        sentence_hits = max(len(sentence & focus) for sentence in sentences)
        overall = len(set().union(*sentences) & focus)
        if sentence_hits == 0:
            continue
        scored.append((sentence_hits, overall, uri))
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    best = scored[0][:2]
    return _unique(
        uri for sentence_hits, overall, uri in scored if (sentence_hits, overall) == best
    )


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

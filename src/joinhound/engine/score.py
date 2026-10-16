# SPDX-License-Identifier: Apache-2.0

"""Path scores and the token budget."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

import tiktoken

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_ENCODER = tiktoken.get_encoding("cl100k_base")


def relevance(query: str, text: str) -> float:
    """Cosine of word counts, scaled into [0.3, 1] so a structural node stays visible."""
    return 0.3 + 0.7 * _cosine(_counts(query), _counts(text))


def path_score(relevance_score: float, edge_scores: tuple[float, ...], depth_decay: float) -> float:
    """Return rel(n, q) times the product of edge scores times decay to the depth."""
    product = 1.0
    for score in edge_scores:
        product *= score
    return relevance_score * product * (depth_decay ** len(edge_scores))


def text_tokens(text: str) -> int:
    """Count cl100k tokens in a text the caller would read."""
    return len(_ENCODER.encode(text))


def truncate_text(text: str, limit: int) -> str:
    """Keep the leading tokens and mark the cut when the text is longer than the limit."""
    tokens = _ENCODER.encode(text)
    if len(tokens) <= limit:
        return text
    kept = tokens[: max(limit - 1, 0)]
    return _ENCODER.decode(kept).rstrip() + "\n"


def content_tokens(content: Mapping[str, Any]) -> int:
    """Count cl100k tokens in the JSON object a caller would read."""
    rendered = json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return len(_ENCODER.encode(rendered))


def _counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _TOKEN.findall(text):
        key = token.casefold()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _cosine(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(count * right.get(token, 0) for token, count in left.items())
    left_norm = math.sqrt(sum(count * count for count in left.values()))
    right_norm = math.sqrt(sum(count * count for count in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

# SPDX-License-Identifier: Apache-2.0

"""Score get_context against questions that name the rows an answer needs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from joinhound.core.config import EngineConfig
from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.core.protocols import LinkMatcher, TabularSource
from joinhound.engine.context import get_context
from joinhound.engine.dictionary import build_dictionary
from joinhound.engine.evaluate import overlap_scores, percentile


@dataclass(frozen=True)
class GoldQuestion:
    """One natural-language question and the rows that answer it."""

    id: str
    query: str
    uris: tuple[str, ...]


@dataclass(frozen=True)
class QuestionScore:
    """How much of one gold set get_context returned."""

    id: str
    precision: float
    recall: float
    ms: int


@dataclass(frozen=True)
class QuestionReport:
    """Macro-averaged scores for a question set."""

    scores: tuple[QuestionScore, ...]

    @property
    def precision(self) -> float:
        return _mean([item.precision for item in self.scores])

    @property
    def recall(self) -> float:
        return _mean([item.recall for item in self.scores])

    def latency_ms(self, rank: float) -> int:
        """Return the nearest-rank latency percentile in milliseconds."""
        return percentile([item.ms for item in self.scores], rank)


def load_questions(path: Path) -> list[GoldQuestion]:
    """Read a question file. Each item has an id, a query, and gold row URIs."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Question file must be a JSON object")
    items = loaded.get("questions")
    if not isinstance(items, list):
        raise ValueError("Question file must contain a questions list")
    questions: list[GoldQuestion] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each question must be an object")
        identifier = item.get("id")
        query = item.get("query")
        uris = item.get("uris")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Each question needs an id")
        if identifier in seen:
            raise ValueError(f"Duplicate question id: {identifier}")
        seen.add(identifier)
        if not isinstance(query, str) or not query:
            raise ValueError(f"Question {identifier} needs a query")
        if not isinstance(uris, list) or not uris or not all(isinstance(uri, str) for uri in uris):
            raise ValueError(f"Question {identifier} needs gold URIs")
        questions.append(GoldQuestion(identifier, query, tuple(uris)))
    return questions


def score_questions(
    questions: Sequence[GoldQuestion],
    source: TabularSource,
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    settings: EngineConfig | None = None,
    passages: Sequence[IndexedPassage] = (),
) -> QuestionReport:
    """Run get_context for each question and macro-average precision and recall."""
    config = settings or EngineConfig()
    dictionary = build_dictionary(source, links)
    scores: list[QuestionScore] = []
    for question in questions:
        response = get_context(
            question.query,
            source,
            links,
            matchers,
            config,
            dictionary=dictionary,
            passages=passages,
        )
        precision, recall = overlap_scores(
            [node.uri for node in response.nodes],
            question.uris,
        )
        scores.append(
            QuestionScore(
                id=question.id,
                precision=precision,
                recall=recall,
                ms=response.stats.ms,
            )
        )
    return QuestionReport(tuple(scores))


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)

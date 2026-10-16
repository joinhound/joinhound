# SPDX-License-Identifier: Apache-2.0

"""The Pagila question file is a stable gold set."""

from pathlib import Path

import pytest

from joinhound.core.uri import parse_uri
from joinhound.engine.questions import load_questions

_GOLD = Path(__file__).resolve().parents[1] / "eval" / "gold" / "pagila_questions.json"


def test_pagila_questions_name_twenty_row_sets() -> None:
    questions = load_questions(_GOLD)

    assert len(questions) == 20
    assert len({question.id for question in questions}) == 20
    for question in questions:
        assert question.query
        assert question.uris
        for uri in question.uris:
            parse_uri(uri)


def test_question_file_rejects_a_duplicate_id(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(
        """
        {"questions": [
          {"id": "one", "query": "ACE GOLDFINGER", "uris": ["pg://pagila/public.film#pk=%7B%22film_id%22%3A2%7D"]},
          {"id": "one", "query": "again", "uris": ["pg://pagila/public.film#pk=%7B%22film_id%22%3A2%7D"]}
        ]}
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate"):
        load_questions(path)

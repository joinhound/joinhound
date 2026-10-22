# SPDX-License-Identifier: Apache-2.0

"""The large library benchmark is deterministic and balanced."""

from dataclasses import replace

import pytest

from joinhound.library_eval import (
    LibraryCase,
    answer_recall,
    archive_phrase,
    case_body,
    questions,
)


def test_case_phrases_are_unique_across_the_full_default_corpus() -> None:
    phrases = {archive_phrase(index) for index in range(10_000)}

    assert len(phrases) == 10_000


def test_question_set_is_balanced_by_kind_and_split() -> None:
    cases = [_case(index) for index in range(1, 101)]

    result = questions(cases, 500)

    assert len(result) == 500
    assert {item.split for item in result} == {"dev", "test"}
    assert {
        kind: sum(item.kind == kind for item in result)
        for kind in {"database", "document", "cross_member", "cross_book", "cross_branch"}
    } == {
        "database": 100,
        "document": 100,
        "cross_member": 100,
        "cross_book": 100,
        "cross_branch": 100,
    }
    assert sum(item.split == "dev" for item in result) == 250
    assert sum(item.split == "test" for item in result) == 250


def test_file_has_the_reference_but_not_the_expected_answers() -> None:
    case = _case(1)

    body = case_body(case)

    assert case.case_ref in body
    assert case.user_name not in body
    assert case.book_title not in body
    assert case.library_name not in body


def test_answer_recall_normalizes_case_and_punctuation() -> None:
    assert answer_recall(["ADA  LOVELACE"], ("Ada-Lovelace",)) == 1
    assert answer_recall([], ("Ada Lovelace",)) == 0


def test_question_count_rejects_an_unbalanced_value() -> None:
    with pytest.raises(ValueError):
        questions([_case(1)], 11)


def _case(index: int) -> LibraryCase:
    template = LibraryCase(
        case_id=1,
        case_ref="CASE-00000001",
        loan_id=1,
        membership_id=2,
        user_id=3,
        user_name="Ada Lovelace",
        copy_id=4,
        book_id=5,
        book_title="Analytical Engines",
        library_id=6,
        library_name="Central Library",
        card_number="CARD-000001",
    )
    return replace(
        template,
        case_id=index,
        case_ref=f"CASE-{index:08d}",
        loan_id=index,
        card_number=f"CARD-{index:06d}",
    )

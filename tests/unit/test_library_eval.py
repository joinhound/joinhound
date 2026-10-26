# SPDX-License-Identifier: Apache-2.0

"""The large library benchmark is deterministic and balanced."""

from dataclasses import replace

import pytest

from joinhound.library_eval import (
    LibraryCase,
    answer_recall,
    archive_phrase,
    case_body,
    distractor_name,
    hard_questions,
    paraphrase,
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
    assert distractor_name(case) in body


def test_hard_questions_hide_the_exact_phrase_and_require_longer_paths() -> None:
    cases = [_linked_case(index) for index in range(1, 11)]

    result = hard_questions(cases, 10)

    assert len(result) == 10
    assert {item.kind for item in result} == {
        "paraphrase_member",
        "paraphrase_book",
        "conflict_member",
        "cross_staff",
        "cross_publisher",
    }
    member = next(item for item in result if item.kind == "paraphrase_member")
    assert archive_phrase(0) not in member.query
    assert paraphrase(0) in member.query
    conflict = next(item for item in result if item.kind == "conflict_member")
    assert distractor_name(cases[0]) not in conflict.query
    assert conflict.answers == (cases[0].user_name,)
    publisher = next(item for item in result if item.kind == "cross_publisher")
    assert cases[0].publisher_name in publisher.answers
    assert any("publishers" in uri for uri in publisher.evidence)


def test_answer_recall_normalizes_case_and_punctuation() -> None:
    assert answer_recall(["ADA  LOVELACE"], ("Ada-Lovelace",)) == 1
    assert answer_recall([], ("Ada Lovelace",)) == 0


def test_question_count_rejects_an_unbalanced_value() -> None:
    with pytest.raises(ValueError):
        questions([_case(1)], 11)


def _linked_case(index: int) -> LibraryCase:
    return replace(
        _case(index),
        publisher_id=20 + index,
        publisher_name=f"Publisher {index}",
        staff_user_id=30 + index,
        staff_name=f"Staff Member {index}",
    )


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

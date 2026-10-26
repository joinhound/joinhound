# SPDX-License-Identifier: Apache-2.0

"""AmbER preparation keeps identifiers hidden and splits paired names together."""

import json
from pathlib import Path

from joinhound.amber_eval import (
    cases,
    distort_alias,
    dossier_body,
    load_questions,
    load_sets,
    write_bundle,
)


def test_amber_cases_are_balanced_and_hide_the_target(tmp_path: Path) -> None:
    source = tmp_path / "amber.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(_set(name, offset))
            for offset, name in enumerate(("Alex Example", "Taylor Example"), start=1)
        )
        + "\n",
        encoding="utf-8",
    )

    selected = cases(load_sets(source, count=2))

    assert [(case.split, case.entity.is_head) for case in selected] == [
        ("dev", True),
        ("dev", False),
        ("test", True),
        ("test", False),
    ]
    for case in selected:
        body = dossier_body(case)
        assert case.dossier_ref in body
        assert case.clue_alias in body
        assert case.entity.qid not in body
        assert case.target.answer not in body
        distorted = dossier_body(case, distort=True)
        surface = distort_alias(case.clue_alias)
        assert surface in distorted
        assert surface.casefold() != case.clue_alias.casefold()
        assert case.clue_alias not in distorted
        assert case.target.answer not in distorted


def test_bundle_records_file_and_database_evidence(tmp_path: Path) -> None:
    source = tmp_path / "amber.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(_set(name, offset))
            for offset, name in enumerate(("Alex Example", "Taylor Example"), start=1)
        )
        + "\n",
        encoding="utf-8",
    )
    selected_sets = load_sets(source, count=2)
    selected = cases(selected_sets)
    fact_ids = {
        (entity.qid, fact.property_id): index
        for index, entity in enumerate(
            (entity for group in selected_sets for entity in group), start=1
        )
        for fact in entity.facts
    }
    # Give every fact a distinct row ID, as the preparation script does.
    fact_ids = {key: index for index, key in enumerate(sorted(fact_ids), start=1)}

    write_bundle(tmp_path / "bundle", selected, fact_ids)
    questions = load_questions(tmp_path / "bundle" / "questions.json")

    assert len(questions) == 4
    assert {question.kind for question in questions} == {"head", "tail"}
    assert all(question.evidence[0].startswith("s3://amber-dossiers/") for question in questions)
    assert all("amber_facts" in question.evidence[1] for question in questions)


def _set(name: str, offset: int) -> dict[str, object]:
    return {
        "name": name,
        "qids": {
            f"Q{offset}01": _entity(True, offset, "Navy", "War"),
            f"Q{offset}02": _entity(False, offset, "Team", "Sport"),
        },
    }


def _entity(
    is_head: bool, offset: int, first_property: str, second_property: str
) -> dict[str, object]:
    suffix = "head" if is_head else "tail"
    return {
        "is_head": is_head,
        "popularity": float(offset),
        "pids": {
            "P1": {
                "property": first_property.casefold(),
                "values": [
                    {
                        "aliases": [f"{first_property} clue {offset} {suffix}"],
                        "additional_aliases": [],
                    }
                ],
            },
            "P2": {
                "property": second_property.casefold(),
                "values": [
                    {
                        "aliases": [f"{second_property} answer {offset} {suffix}"],
                        "additional_aliases": [],
                    }
                ],
            },
        },
    }

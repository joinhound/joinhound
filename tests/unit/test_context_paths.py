# SPDX-License-Identifier: Apache-2.0

"""Context answers keep answer-bearing paths and leave the rest expandable."""

from joinhound.core.config import EngineConfig
from joinhound.core.models import LinkDraft
from joinhound.engine.context import get_context, read_record
from joinhound.engine.score import has_novel_text, mentions_collection, mentions_phrase
from joinhound.matchers import DeclaredFkMatcher
from joinhound.profiler.profile import link_id
from joinhound.testing.memory import MemoryTabularSource


def test_a_named_answer_outranks_identifier_only_branches() -> None:
    source = _source()
    result = get_context(
        "Which member has card CARD-000001?",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=10, max_paths=1, budget_tokens=100_000),
        max_depth=1,
        clock=_frozen,
    )

    assert {node.collection for node in result.nodes} == {"cards", "users"}
    user = next(node for node in result.nodes if node.collection == "users")
    assert user.content["name"] == "Ada Lovelace"
    assert "id" not in user.content
    assert result.truncated
    assert result.expandable


def test_reverse_expansion_after_the_seed_stays_narrow() -> None:
    source = _source()
    result = get_context(
        "Which member has card CARD-000001?",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=10, child_fanout=1, max_paths=16, budget_tokens=100_000),
        max_depth=2,
        clock=_frozen,
    )

    assert sum(node.collection == "payments" for node in result.nodes) == 1
    assert any(node.content.get("name") == "Ada Lovelace" for node in result.nodes)


def test_get_record_returns_columns_omitted_from_the_context_graph() -> None:
    source = _source()
    result = get_context(
        "Which member has card CARD-000001?",
        source,
        _links(),
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(max_paths=1, budget_tokens=100_000),
        max_depth=1,
        clock=_frozen,
    )
    user = next(node for node in result.nodes if node.collection == "users")

    record = read_record(user.uri, source)

    assert record.content["name"] == "Ada Lovelace"
    assert record.content["id"] == 7


def test_extra_path_slots_stay_with_the_named_collection() -> None:
    source = MemoryTabularSource(
        {
            "films": [{"id": 1, "title": "ACADEMY DINOSAUR"}],
            "actors": [
                {"id": index, "film_id": 1, "name": f"Actor {index}"} for index in range(1, 5)
            ],
            "tickets": [{"id": index, "film_id": 1} for index in range(1, 11)],
        }
    )
    specs = (
        ("actors", "film_id", "films", "id"),
        ("tickets", "film_id", "films", "id"),
    )
    links = [
        LinkDraft(
            link_id=link_id(*spec),
            src_collection=spec[0],
            src_column=spec[1],
            dst_collection=spec[2],
            dst_column=spec[3],
            match_type="declared_fk",
            origin="catalog_fk",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        )
        for spec in specs
    ]

    result = get_context(
        "Who acts in ACADEMY DINOSAUR?",
        source,
        links,
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=20, max_paths=6, budget_tokens=100_000),
        max_depth=1,
        clock=_frozen,
    )

    names = {str(node.content.get("name")) for node in result.nodes if node.collection == "actors"}
    assert names == {f"Actor {index}" for index in range(1, 5)}
    assert sum(node.collection == "tickets" for node in result.nodes) < 4


def test_forward_links_stay_on_the_beam_ahead_of_reverse_distractors() -> None:
    source = MemoryTabularSource(
        {
            "cards": [{"id": 1, "card_number": "CARD-000001", "user_id": 7}],
            "users": [{"id": 7, "profile_id": 9}],
            "profiles": [{"id": 9, "name": "Ada Lovelace"}],
            "loans": [
                {
                    "id": index,
                    "card_id": 1,
                    "note": "CARD-000001 member card",
                }
                for index in range(1, 8)
            ],
        }
    )
    links = [
        LinkDraft(
            link_id=link_id(*spec),
            src_collection=spec[0],
            src_column=spec[1],
            dst_collection=spec[2],
            dst_column=spec[3],
            match_type="declared_fk",
            origin="catalog_fk",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        )
        for spec in (
            ("cards", "user_id", "users", "id"),
            ("users", "profile_id", "profiles", "id"),
            ("loans", "card_id", "cards", "id"),
        )
    ]

    result = get_context(
        "Which profile has card CARD-000001?",
        source,
        links,
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=10, beam_width=1, max_paths=4, budget_tokens=100_000),
        max_depth=2,
        clock=_frozen,
    )

    assert any(node.content.get("name") == "Ada Lovelace" for node in result.nodes)


def test_an_asked_property_keeps_one_chain() -> None:
    source = MemoryTabularSource(
        {
            "people": [{"id": 1, "name": "Ada Lovelace"}],
            "facts": [
                {"id": 1, "person_id": 1, "property_name": "sport", "answer": "chess"},
                {"id": 2, "person_id": 1, "property_name": "title", "answer": "captain"},
                {"id": 3, "person_id": 1, "property_name": "sport", "answer": "curling"},
            ],
        }
    )
    links = [
        LinkDraft(
            link_id=link_id("facts", "person_id", "people", "id"),
            src_collection="facts",
            src_column="person_id",
            dst_collection="people",
            dst_column="id",
            match_type="declared_fk",
            origin="catalog_fk",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        )
    ]

    result = get_context(
        "What is Ada Lovelace's sport?",
        source,
        links,
        {"declared_fk": DeclaredFkMatcher(source)},
        EngineConfig(fanout=10, max_paths=8, budget_tokens=100_000),
        max_depth=2,
        clock=_frozen,
    )

    answers = {str(node.content.get("answer")) for node in result.nodes}
    assert "captain" not in answers
    assert answers & {"chess", "curling"}
    assert sum(node.collection == "facts" for node in result.nodes) == 1


def test_path_ranking_prefers_new_words_and_named_collections() -> None:
    assert has_novel_text("CARD-000001", "Ada Lovelace")
    assert not has_novel_text("Ada Lovelace", "Ada Lovelace")
    assert mentions_collection("Which book was borrowed?", "pg://library/public.books")
    assert not mentions_collection("Which member has a card?", "pg://library/public.users")
    assert mentions_phrase("What is the military branch?", "military branch")
    assert not mentions_phrase("What is the sport?", "id")
    assert not mentions_phrase("What is the member of sports team?", "sport")


def _frozen() -> float:
    return 0.0


def _source() -> MemoryTabularSource:
    return MemoryTabularSource(
        {
            "cards": [{"id": 1, "card_number": "CARD-000001", "user_id": 7}],
            "users": [{"id": 7, "name": "Ada Lovelace"}],
            "loans": [
                {"id": 10, "card_id": 1},
                {"id": 11, "card_id": 1},
                {"id": 12, "card_id": 1},
            ],
            "payments": [
                {"id": 100, "loan_id": 10, "note": "one"},
                {"id": 101, "loan_id": 10, "note": "two"},
                {"id": 102, "loan_id": 10, "note": "three"},
            ],
        }
    )


def _links() -> list[LinkDraft]:
    specs = (
        ("cards", "user_id", "users", "id"),
        ("loans", "card_id", "cards", "id"),
        ("payments", "loan_id", "loans", "id"),
    )
    return [
        LinkDraft(
            link_id=link_id(*spec),
            src_collection=spec[0],
            src_column=spec[1],
            dst_collection=spec[2],
            dst_column=spec[3],
            match_type="declared_fk",
            origin="catalog_fk",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        )
        for spec in specs
    ]

# SPDX-License-Identifier: Apache-2.0

"""Passage seeds, reciprocal rank fusion, and the access filter."""

from joinhound.core.config import EngineConfig
from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.core.protocols import Embedder
from joinhound.engine.context import get_context
from joinhound.engine.passages import lexical_rank, reciprocal_rank_fusion
from joinhound.matchers.documents import DocumentMatcher, Passage
from joinhound.testing.memory import MemoryTabularSource

_LEGAL = "s3://docs/legal.txt#page=1&bbox=0.0,0.0,1.0,1.0"
_SECRET = "s3://finance/secret.txt#page=1&bbox=0.0,0.0,1.0,1.0"


class _Direction(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0 if "beta" in text else 0.0, 1.0 if "alpha" in text else 0.0] for text in texts]


def test_lexical_rank_keeps_a_note_when_the_question_adds_words() -> None:
    passages = [
        _passage("s3://docs/other.txt", "s3://docs/", "Circulation case note"),
        _passage(
            "s3://docs/match.txt", "s3://docs/", "Observation: amber anchor beside the arcade"
        ),
    ]

    ranked = lexical_rank(
        "Which publisher issued the book connected to 'arcade observation amber anchor'?",
        passages,
    )

    assert ranked == ["s3://docs/match.txt"]


def test_lexical_rank_prefers_words_that_sit_together() -> None:
    passages = [
        _passage(
            "s3://docs/scattered.txt",
            "s3://docs/",
            "Observation was filed. Amber was discussed. Much later an anchor beside the arcade.",
        ),
        _passage(
            "s3://docs/tight.txt",
            "s3://docs/",
            "Observation: amber anchor beside the arcade.",
        ),
    ]

    ranked = lexical_rank("arcade observation amber anchor", passages)

    assert ranked == ["s3://docs/tight.txt"]


def test_fusion_adds_reciprocal_ranks() -> None:
    fused = reciprocal_rank_fusion([["b"], ["b", "a"]])

    assert fused == ["b", "a"]


def test_lexical_and_semantic_seeds_are_both_returned() -> None:
    passages = [
        _passage("s3://docs/beta.txt", "s3://docs/", "nothing written here", (0.0, 1.0)),
        _passage("s3://docs/alpha.txt", "s3://docs/", "alpha is the word", (1.0, 0.0)),
    ]

    result = get_context(
        "alpha",
        MemoryTabularSource({}),
        [],
        {},
        EngineConfig(budget_tokens=100_000),
        passages=passages,
        embedder=_Direction(),
        clock=_frozen,
    )

    assert {node.uri for node in result.nodes} == {passages[0].uri, passages[1].uri}
    assert {node.kind for node in result.nodes} == {"passage"}


def test_an_inaccessible_passage_never_appears() -> None:
    source = MemoryTabularSource(
        {"films": [{"id": 1, "title": "ACADEMY DINOSAUR", "code": "ACME-1"}]}
    )
    legal = _passage(_LEGAL, "s3://docs/", "shipment ACME-1", roles=("legal",))
    secret = _passage(_SECRET, "s3://finance/", "shipment ACME-1", roles=("finance",))
    passages = [legal, secret]
    matcher = DocumentMatcher(
        source,
        [
            Passage(legal.collection_id, {"uri": legal.uri}, legal.text),
            Passage(secret.collection_id, {"uri": secret.uri}, secret.text),
        ],
    )

    result = get_context(
        "ACADEMY DINOSAUR",
        source,
        [_document_link()],
        {"column_documents": matcher},
        EngineConfig(fanout=10, budget_tokens=100_000),
        max_depth=1,
        passages=passages,
        roles=["legal"],
        clock=_frozen,
    )

    rendered = result.model_dump_json()
    assert _SECRET not in rendered
    assert "finance" not in rendered
    assert _LEGAL in rendered
    reached = [node for node in result.nodes if node.uri == _LEGAL]
    assert len(reached) == 1
    assert reached[0].kind == "passage"
    assert reached[0].seed is False


def test_a_passage_does_not_spread_to_other_documents_through_a_shared_value() -> None:
    source = MemoryTabularSource(
        {"films": [{"id": 1, "title": "ACADEMY DINOSAUR", "code": "ACME-1"}]}
    )
    first = _passage("s3://docs/first.txt", "s3://docs/", "alpha note for ACME-1")
    second = _passage("s3://docs/second.txt", "s3://docs/", "unrelated note for ACME-1")
    passages = [first, second]
    matcher = DocumentMatcher(
        source,
        [
            Passage(first.collection_id, {"uri": first.uri}, first.text),
            Passage(second.collection_id, {"uri": second.uri}, second.text),
        ],
    )

    result = get_context(
        "alpha note",
        source,
        [_document_link()],
        {"column_documents": matcher},
        EngineConfig(fanout=10, budget_tokens=100_000),
        max_depth=2,
        passages=passages,
        clock=_frozen,
    )

    assert first.uri in {node.uri for node in result.nodes}
    assert second.uri not in {node.uri for node in result.nodes}


def _passage(
    uri: str,
    collection_id: str,
    text: str,
    embedding: tuple[float, float] = (0.0, 0.0),
    roles: tuple[str, ...] = (),
) -> IndexedPassage:
    return IndexedPassage(
        uri=uri,
        collection_id=collection_id,
        text=text,
        page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        roles=roles,
        embedding=embedding,
    )


def _document_link() -> LinkDraft:
    return LinkDraft(
        link_id="films.code",
        src_collection="films",
        src_column="code",
        dst_collection="s3://docs/",
        match_type="column_documents",
        origin="profile",
        confidence=1.0,
        status="approved",
    )


def _frozen() -> float:
    return 0.0

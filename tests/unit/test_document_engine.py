# SPDX-License-Identifier: Apache-2.0

"""Passage seeds, reciprocal rank fusion, and the access filter."""

from joinhound.core.config import EngineConfig
from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.core.protocols import Embedder
from joinhound.engine.context import get_context
from joinhound.engine.passages import reciprocal_rank_fusion
from joinhound.matchers.documents import DocumentMatcher, Passage
from joinhound.testing.memory import MemoryTabularSource

_LEGAL = "s3://docs/legal.txt#page=1&bbox=0.0,0.0,1.0,1.0"
_SECRET = "s3://finance/secret.txt#page=1&bbox=0.0,0.0,1.0,1.0"


class _Direction(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0 if "beta" in text else 0.0, 1.0 if "alpha" in text else 0.0] for text in texts]


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

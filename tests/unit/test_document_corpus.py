# SPDX-License-Identifier: Apache-2.0

"""The document corpus retrieves digital PDFs and misses scans."""

from pathlib import Path

from joinhound.core.config import EngineConfig
from joinhound.core.models import (
    CollectionProfile,
    ColumnProfile,
    IndexedPassage,
    ProfileContext,
)
from joinhound.core.uri import S3Uri, build_uri
from joinhound.engine.evaluate import record_key
from joinhound.engine.questions import GoldQuestion, load_questions, score_questions
from joinhound.evalset import CorpusDocument, CorpusQuestion, generate_corpus
from joinhound.index.chunks import chunk_blocks, normalize_blocks
from joinhound.matchers.documents import DocumentMatcher, Passage
from joinhound.parsers import PdfParser
from joinhound.testing.memory import MemoryTabularSource

_GOLD = Path(__file__).parents[1] / "eval" / "gold" / "document_questions.json"
_RECALL_FLOOR = 0.78


def test_document_questions_match_the_generator() -> None:
    _documents, questions = generate_corpus()

    assert len(questions) == 50
    assert load_questions(_GOLD) == [_gold(question) for question in questions]


def test_get_context_recall_on_the_document_corpus() -> None:
    documents, questions = generate_corpus()
    assert len(documents) == 200
    assert sum(document.scan for document in documents) == 40
    report = score_questions(
        load_questions(_GOLD),
        MemoryTabularSource({}),
        [],
        {},
        EngineConfig(budget_tokens=100_000),
        _passages(documents),
    )

    assert report.recall >= _RECALL_FLOOR
    assert report.precision >= 0.6
    assert report.latency_ms(95) < 2000
    by_id = {score.id: score for score in report.scores}
    scans = {document.key for document in documents if document.scan}
    for question in questions:
        expected = 0.0 if question.key in scans else 1.0
        assert by_id[question.id].recall == expected


def test_sampled_codes_link_to_the_corpus() -> None:
    documents, _questions = generate_corpus()
    passages = _passages(documents)
    source = MemoryTabularSource(
        {
            "orders": [
                {"id": index, "code": document.code} for index, document in enumerate(documents)
            ]
        }
    )
    candidate = DocumentMatcher(
        source,
        [Passage("s3://corpus/", {"uri": passage.uri}, passage.text) for passage in passages],
    ).discover(
        ColumnProfile(collection_id="orders", column_name="code", type_class="text"),
        CollectionProfile(collection_id="s3://corpus/"),
        ProfileContext(),
    )

    assert candidate is not None
    assert candidate.confidence >= 0.3


def test_a_box_does_not_change_the_document_key() -> None:
    plain = "s3://corpus/invoices/invoice-0000.pdf"
    located = build_uri(
        S3Uri("corpus", "invoices/invoice-0000.pdf", page=1, bbox=(1.0, 2.0, 3.0, 4.0))
    )

    assert record_key(plain) == record_key(located)


def _passages(documents: tuple[CorpusDocument, ...]) -> list[IndexedPassage]:
    parser = PdfParser()
    found: list[IndexedPassage] = []
    for document in documents:
        blocks = parser.parse(document.data)
        if document.scan:
            assert blocks == []
            continue
        chunks = chunk_blocks(normalize_blocks(blocks))
        assert chunks
        assert any(document.code in chunk.text for chunk in chunks)
        for chunk in chunks:
            found.append(
                IndexedPassage(
                    uri=build_uri(S3Uri("corpus", document.key, page=chunk.page, bbox=chunk.bbox)),
                    collection_id="s3://corpus/",
                    text=chunk.text,
                    page=chunk.page,
                    bbox=chunk.bbox,
                )
            )
    return found


def _gold(question: CorpusQuestion) -> GoldQuestion:
    return GoldQuestion(question.id, question.query, (f"s3://corpus/{question.key}",))

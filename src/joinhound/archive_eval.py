# SPDX-License-Identifier: Apache-2.0

"""Questions over the CC0 historical-document archive and its highlight files."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from joinhound.core.config import EngineConfig
from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.core.protocols import TabularSource
from joinhound.core.uri import PgUri, S3Uri, build_uri
from joinhound.engine.questions import GoldQuestion, score_questions
from joinhound.matchers import DeclaredFkMatcher
from joinhound.matchers.documents import DocumentMatcher, Passage
from joinhound.profiler.profile import link_id

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_WINDOW = 5
_QUESTIONS = 8
_COLLECTION = "s3://archives/"
_MIN_VALUE = 3

_TABLES = (
    "document_authors",
    "document_eras",
    "document_materials",
    "documents",
    "document_events",
)


@dataclass(frozen=True)
class ArchiveGap:
    """Recall of each question group with the files and without them."""

    catalog_without: float
    catalog_with: float
    file_without: float
    file_with: float
    bridge_without: float
    bridge_with: float


@dataclass(frozen=True)
class ArchiveDataset:
    """Catalog rows, highlight files, and the three question groups."""

    rows: dict[str, list[dict[str, object]]]
    passages: tuple[IndexedPassage, ...]
    catalog: tuple[GoldQuestion, ...]
    files: tuple[GoldQuestion, ...]
    bridge: tuple[GoldQuestion, ...]


def load_archive(path: Path) -> ArchiveDataset:
    """Read the vendored JSON and the questions derived from it."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Archive dataset must be a JSON object")
    authors = _records(loaded, "document_authors")
    eras = _records(loaded, "document_eras")
    materials = _records(loaded, "document_materials")
    documents = [_document(row) for row in _records(loaded, "documents")]
    events = _records(loaded, "document_events")
    highlights = _records(loaded, "document_highlights")
    rows = {
        "document_authors": authors,
        "document_eras": eras,
        "document_materials": materials,
        "documents": documents,
        "document_events": events,
    }
    ordered = sorted(highlights, key=lambda item: _int(item["id"]))
    passages = tuple(_passage(row) for row in ordered)
    catalog, file_questions, bridge = _questions(rows, ordered, passages)
    return ArchiveDataset(rows, passages, catalog, file_questions, bridge)


def measure(source: TabularSource, dataset: ArchiveDataset) -> ArchiveGap:
    """Score the same questions against the catalog alone and with the highlight files."""
    links = _links(source)
    matchers = {
        "declared_fk": DeclaredFkMatcher(source),
        "column_documents": DocumentMatcher(
            source,
            [
                Passage(passage.collection_id, {"uri": passage.uri}, passage.text)
                for passage in dataset.passages
            ],
        ),
    }
    settings = EngineConfig(budget_tokens=100_000)

    def recall(questions: tuple[GoldQuestion, ...], passages: tuple[IndexedPassage, ...]) -> float:
        return score_questions(questions, source, links, matchers, settings, passages).recall

    return ArchiveGap(
        catalog_without=recall(dataset.catalog, ()),
        catalog_with=recall(dataset.catalog, dataset.passages),
        file_without=recall(dataset.files, ()),
        file_with=recall(dataset.files, dataset.passages),
        bridge_without=recall(dataset.bridge, ()),
        bridge_with=recall(dataset.bridge, dataset.passages),
    )


def file_name(highlight_id: int) -> str:
    """Return the repo-relative file name of one highlight."""
    return f"highlight-{highlight_id:04d}.txt"


def file_body(document_id: int, highlight_text: str) -> str:
    """Return the file body. The code is the only catalog value added to the prose."""
    return f"{archive_code(document_id)}\n{highlight_text}\n"


def archive_code(document_id: int) -> str:
    """Return the code stored on a document and copied into its highlight files."""
    return f"ARC-{document_id:04d}"


def _document(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": _int(row["id"]),
        "title": _text(row["title"]),
        "document_era_id": _int(row["document_era_id"]),
        "author_id": _int(row["author_id"]),
        "format": _text(row["format"]),
        "condition": _text(row["condition"]),
        "archive_code": archive_code(_int(row["id"])),
    }


def _passage(row: Mapping[str, object]) -> IndexedPassage:
    highlight_id = _int(row["id"])
    document_id = _int(row["document_id"])
    key = f"highlights/{file_name(highlight_id)}"
    return IndexedPassage(
        uri=build_uri(S3Uri(source="archives", key=key)),
        collection_id=_COLLECTION,
        text=file_body(document_id, _text(row["highlight_text"])),
        page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
    )


def _questions(
    rows: Mapping[str, Sequence[Mapping[str, object]]],
    highlights: Sequence[Mapping[str, object]],
    passages: Sequence[IndexedPassage],
) -> tuple[tuple[GoldQuestion, ...], tuple[GoldQuestion, ...], tuple[GoldQuestion, ...]]:
    by_highlight = {
        _int(row["id"]): passage for row, passage in zip(highlights, passages, strict=True)
    }
    catalog = _catalog_questions(rows["document_authors"])
    phrases = _phrases(rows, highlights)
    file_questions: list[GoldQuestion] = []
    bridge: list[GoldQuestion] = []
    for highlight_id, phrase, document_id in phrases:
        passage = by_highlight[highlight_id]
        file_questions.append(GoldQuestion(f"file-{highlight_id}", phrase, (passage.uri,)))
        bridge.append(
            GoldQuestion(
                f"bridge-{highlight_id}",
                phrase,
                (passage.uri, _row_uri("documents", document_id)),
            )
        )
    return (tuple(catalog), tuple(file_questions), tuple(bridge))


def _catalog_questions(authors: Sequence[Mapping[str, object]]) -> list[GoldQuestion]:
    names = Counter(_text(row["full_name"]) for row in authors)
    questions: list[GoldQuestion] = []
    for row in sorted(authors, key=lambda item: _int(item["id"])):
        name = _text(row["full_name"])
        if names[name] != 1:
            continue
        author_id = _int(row["id"])
        questions.append(
            GoldQuestion(f"author-{author_id}", name, (_row_uri("document_authors", author_id),))
        )
        if len(questions) == _QUESTIONS:
            break
    if len(questions) != _QUESTIONS:
        raise ValueError("The archive does not have enough unique author names")
    return questions


def _phrases(
    rows: Mapping[str, Sequence[Mapping[str, object]]],
    highlights: Sequence[Mapping[str, object]],
) -> list[tuple[int, str, int]]:
    needles = _needles(rows)
    seen: Counter[str] = Counter()
    windows: list[tuple[str, int, str, int]] = []
    for row in sorted(highlights, key=lambda item: _int(item["id"])):
        tokens = _TOKEN.findall(_text(row["highlight_text"]))
        highlight_id = _int(row["id"])
        document_id = _int(row["document_id"])
        for index in range(0, max(len(tokens) - _WINDOW + 1, 0)):
            phrase = " ".join(tokens[index : index + _WINDOW])
            folded = phrase.casefold()
            seen[folded] += 1
            windows.append((folded, highlight_id, phrase, document_id))
    chosen: list[tuple[int, str, int]] = []
    used_documents: set[int] = set()
    for folded, highlight_id, phrase, document_id in windows:
        if seen[folded] != 1 or document_id in used_documents or _contaminated(phrase, needles):
            continue
        used_documents.add(document_id)
        chosen.append((highlight_id, phrase, document_id))
        if len(chosen) == _QUESTIONS:
            return chosen
    raise ValueError("The archive does not have enough distinctive highlight phrases")


def _needles(rows: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[str, ...]:
    values: list[str] = []
    for table in _TABLES:
        for row in rows[table]:
            for key, value in row.items():
                if key == "id" or not isinstance(value, str):
                    continue
                if len(value) >= _MIN_VALUE:
                    values.append(value.casefold())
    return tuple(sorted(set(values), key=len, reverse=True))


def _contaminated(phrase: str, needles: Sequence[str]) -> bool:
    haystack = f" {phrase.casefold()} "
    return any(f" {needle} " in haystack for needle in needles)


def _links(source: TabularSource) -> list[LinkDraft]:
    drafts: list[LinkDraft] = []
    for foreign_key in source.declared_links():
        if len(foreign_key.src_columns) != 1 or len(foreign_key.dst_columns) != 1:
            continue
        src_column = foreign_key.src_columns[0]
        dst_column = foreign_key.dst_columns[0]
        drafts.append(
            LinkDraft(
                link_id=link_id(
                    foreign_key.src_collection,
                    src_column,
                    foreign_key.dst_collection,
                    dst_column,
                ),
                src_collection=foreign_key.src_collection,
                src_column=src_column,
                dst_collection=foreign_key.dst_collection,
                dst_column=dst_column,
                match_type="declared_fk",
                origin="catalog_fk",
                confidence=1.0,
                status="approved",
                cardinality="N:1",
            )
        )
    documents = [
        info.collection_id
        for info in source.list_collections()
        if info.collection_id.rsplit(".", 1)[-1].rsplit("/", 1)[-1] == "documents"
    ]
    if len(documents) != 1:
        raise ValueError("The archive source must contain one documents collection")
    drafts.append(
        LinkDraft(
            link_id="documents.archive_code",
            src_collection=documents[0],
            src_column="archive_code",
            dst_collection=_COLLECTION,
            match_type="column_documents",
            origin="profile",
            confidence=1.0,
            status="approved",
        )
    )
    return drafts


def _row_uri(table: str, row_id: int) -> str:
    return build_uri(PgUri(source="archives", schema="public", table=table, pk={"id": row_id}))


def _records(payload: Mapping[str, object], key: str) -> list[dict[str, object]]:
    raw = payload.get(key)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Archive dataset is missing {key}")
    records: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{key} must contain objects")
        records.append({str(field): value for field, value in item.items()})
    return records


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a non-empty string")
    return value


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer")
    return value

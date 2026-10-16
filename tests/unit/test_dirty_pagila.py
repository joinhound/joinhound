# SPDX-License-Identifier: Apache-2.0

"""Dirty Pagila-shaped columns still resolve through normalized and fuzzy links."""

from joinhound.core.config import EngineConfig
from joinhound.core.models import ColumnProfile, Link, LinkDraft, ProfileContext, QueryContext
from joinhound.core.uri import PgUri, build_uri
from joinhound.dirty import DirtyColumn, generate_dirty_pagila
from joinhound.engine.questions import GoldQuestion, score_questions
from joinhound.matchers import FuzzyMatcher, NormalizedMatcher
from joinhound.testing.memory import MemoryTabularSource


def test_dirty_columns_resolve_and_get_context_walks_them() -> None:
    tables, columns = generate_dirty_pagila()
    source = MemoryTabularSource(tables)
    normalized = NormalizedMatcher(source)
    fuzzy = FuzzyMatcher(source)
    recalls = {column.name: _recall(column, normalized, fuzzy) for column in columns}

    assert recalls == {"email": 0.9, "phone": 1.0, "code": 1.0}
    assert _context_recall(source, columns, normalized, fuzzy) == 1.0


def _recall(
    column: DirtyColumn,
    normalized: NormalizedMatcher,
    fuzzy: FuzzyMatcher,
) -> float:
    matcher = normalized if column.match_type == "normalized" else fuzzy
    link = Link(
        link_id=column.name,
        match_type=column.match_type,
        src_collection=column.src_collection,
        src_column=column.src_column,
        dst_collection=column.dst_collection,
        dst_column=column.dst_column,
        normalize_sql=column.expression,
    )
    found = matcher.resolve(
        link,
        [dirty for _row, dirty, _clean in column.pairs],
        QueryContext(limit=len(column.pairs)),
    )
    hits = {match.value for match in found}
    return sum(dirty in hits for _row, dirty, _clean in column.pairs) / len(column.pairs)


def _context_recall(
    source: MemoryTabularSource,
    columns: tuple[DirtyColumn, ...],
    normalized: NormalizedMatcher,
    fuzzy: FuzzyMatcher,
) -> float:
    questions = []
    for column in columns:
        _row, dirty, _clean = column.pairs[1]
        questions.append(
            GoldQuestion(
                id=column.name,
                query=dirty,
                uris=(build_uri(PgUri("memory", "public", column.dst_collection, {"id": _row})),),
            )
        )
    drafts = [
        LinkDraft(
            link_id=column.name,
            src_collection=column.src_collection,
            src_column=column.src_column,
            dst_collection=column.dst_collection,
            dst_column=column.dst_column,
            match_type=column.match_type,
            origin="discovered",
            normalize_sql=column.expression,
            confidence=1.0,
            status="approved",
        )
        for column in columns
    ]
    report = score_questions(
        questions,
        source,
        drafts,
        {"normalized": normalized, "fuzzy": fuzzy},
        EngineConfig(budget_tokens=100_000),
    )
    return report.recall


def test_discovery_rejects_an_unrelated_column() -> None:
    tables, columns = generate_dirty_pagila()
    source = MemoryTabularSource(tables)
    email = columns[0]
    profile = ProfileContext(sample_values=40)
    src = ColumnProfile(collection_id="intake", column_name="email", type_class="text")
    unrelated = ColumnProfile(collection_id="film", column_name="code", type_class="text")

    assert NormalizedMatcher(source).discover(src, unrelated, profile) is None
    assert email.expression == "fold"

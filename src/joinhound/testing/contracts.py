# SPDX-License-Identifier: Apache-2.0

"""Contract checks that every source and matcher implementation must pass."""

from joinhound.core.models import (
    CollectionProfile,
    ColumnProfile,
    Link,
    ProfileContext,
    QueryContext,
)
from joinhound.core.protocols import DocumentSource, LinkMatcher, TabularSource


def check_tabular_source(
    source: TabularSource,
    *,
    collection_id: str,
    column: str,
    value: str,
    key: dict[str, object],
) -> None:
    """Check the read operations of a tabular source against one known row."""
    collections = {item.collection_id for item in source.list_collections()}
    assert collection_id in collections

    stats = {item.column_name for item in source.column_stats(collection_id)}
    assert column in stats

    sample = source.sample(collection_id, [column], 1)
    assert len(sample) == 1
    assert sample[0][column] == value

    matches = source.find_values(collection_id, column, [value], "exact")
    assert any(match.value == value and match.pk == key for match in matches)

    records = source.fetch_by_keys(collection_id, [key])
    assert any(record.pk == key and record.values[column] == value for record in records)

    scanned = list(source.scan_column(collection_id, column, None))
    assert any(pk == key and scanned_value == value for pk, scanned_value in scanned)


def check_document_source(source: DocumentSource, *, name: str, content: bytes) -> None:
    """Check the read operations of a document source against one known object."""
    assert any(item.kind == "documents" for item in source.list_collections())
    documents = list(source.changes_since("docs", None))
    matching = [document for document in documents if document.uri.endswith(name)]
    assert matching
    assert source.read(matching[0]) == content
    access = source.acl(matching[0])
    assert access is not None


def check_link_matcher(
    matcher: LinkMatcher,
    *,
    src: ColumnProfile,
    dst: ColumnProfile | CollectionProfile,
    unrelated: ColumnProfile | CollectionProfile,
    link: Link,
    values: list[str],
    missing_value: str,
    expected_value: str,
    expected_pk: dict[str, object],
) -> None:
    """Check discovery and resolution against one known relationship and one miss.

    ``values`` must resolve to at least two destination rows so the limit is observable.
    """
    profile = ProfileContext()
    candidate = matcher.discover(src, dst, profile)
    assert candidate is not None
    assert candidate.match_type == matcher.match_type
    assert 0.0 <= candidate.confidence <= 1.0
    assert matcher.discover(src, unrelated, profile) is None

    found = matcher.resolve(link, values, QueryContext())
    assert len(found) >= 2
    assert any(
        match.value == expected_value and match.pk == expected_pk and 0.0 <= match.score <= 1.0
        for match in found
    )
    assert matcher.resolve(link, [missing_value], QueryContext()) == []
    assert len(matcher.resolve(link, values, QueryContext(limit=1))) == 1

# SPDX-License-Identifier: Apache-2.0

"""Contract checks that every source implementation must pass."""

from joinhound.core.protocols import DocumentSource, TabularSource


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

# SPDX-License-Identifier: Apache-2.0

"""Column-to-document matching beyond the shared contract."""

from joinhound.core.models import (
    CollectionProfile,
    ColumnProfile,
    Link,
    ProfileContext,
    QueryContext,
)
from joinhound.matchers.documents import DocumentMatcher, Passage
from joinhound.testing.memory import MemoryTabularSource

_LINK = Link(
    link_id="orders.code",
    match_type="column_documents",
    src_collection="orders",
    src_column="code",
    dst_collection="s3://docs/",
)


def test_a_value_in_every_fragment_is_not_a_link() -> None:
    source = MemoryTabularSource({"orders": [{"id": 1, "code": "COMMON"}]})
    passages = [
        Passage("s3://docs/", {"chunk_id": 1}, "COMMON appears here"),
        Passage("s3://docs/", {"chunk_id": 2}, "COMMON appears there"),
    ]

    candidate = DocumentMatcher(source, passages).discover(
        _column(),
        CollectionProfile(collection_id="s3://docs/"),
        ProfileContext(),
    )

    assert candidate is None


def test_trigram_resolves_a_near_word() -> None:
    source = MemoryTabularSource({"orders": [{"id": 1, "code": "address"}]})
    passages = [Passage("s3://docs/", {"chunk_id": 1}, "the adress of the invoice")]

    found = DocumentMatcher(source, passages).resolve(_LINK, ["address"], QueryContext())

    assert len(found) == 1
    assert found[0].pk == {"chunk_id": 1}
    assert 0.6 <= found[0].score < 1.0


def test_a_fragment_points_back_at_rows() -> None:
    source = MemoryTabularSource(
        {
            "orders": [
                {"id": 1, "code": "ACME-1"},
                {"id": 2, "code": "ACME-2"},
            ]
        }
    )
    matcher = DocumentMatcher(source, [])

    found = matcher.mentions(_LINK, "Invoice for ACME-1 shipped today", QueryContext())

    assert [match.pk for match in found] == [{"id": 1}]
    assert found[0].value == "ACME-1"


def _column() -> ColumnProfile:
    return ColumnProfile(collection_id="orders", column_name="code", type_class="text")

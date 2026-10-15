# SPDX-License-Identifier: Apache-2.0

"""The packaged source contracts, exercised by the in-memory implementations."""

import pytest

from joinhound.core.models import DeclaredFK
from joinhound.testing.contracts import check_document_source, check_tabular_source
from joinhound.testing.memory import MemoryDocumentSource, MemoryTabularSource

_SOURCES = [
    MemoryTabularSource(
        {"customers": [{"id": 1, "email": "a@example.com"}]},
        [
            DeclaredFK(
                src_collection="orders",
                src_columns=["customer_id"],
                dst_collection="customers",
                dst_columns=["id"],
            )
        ],
    )
]


@pytest.mark.parametrize("source", _SOURCES)
def test_tabular_contract(source: MemoryTabularSource) -> None:
    assert source.declared_links()[0].dst_collection == "customers"
    check_tabular_source(
        source,
        collection_id="customers",
        column="email",
        value="a@example.com",
        key={"id": 1},
    )


def test_document_contract() -> None:
    source = MemoryDocumentSource({"note.txt": b"hello"}, roles=["legal"])

    check_document_source(source, name="note.txt", content=b"hello")
    access = source.acl(next(source.changes_since("docs", None)))
    assert access is not None
    assert access.roles == ["legal"]

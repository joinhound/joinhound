# SPDX-License-Identifier: Apache-2.0

"""The packaged matcher contract, exercised by the built-in equality matchers."""

from joinhound.core.models import CollectionProfile, ColumnProfile, DeclaredFK, Link
from joinhound.matchers import (
    DeclaredFkMatcher,
    DocumentMatcher,
    ExactMatcher,
    FuzzyMatcher,
    NormalizedMatcher,
)
from joinhound.matchers.documents import Passage
from joinhound.testing.contracts import check_link_matcher
from joinhound.testing.memory import MemoryTabularSource

_SOURCE = MemoryTabularSource(
    {
        "orders": [
            {"id": 10, "customer_id": 1, "email": "a@example.com"},
            {"id": 11, "customer_id": 2, "email": "b@example.com"},
        ],
        "customers": [
            {"id": 1, "email": "a@example.com"},
            {"id": 2, "email": "b@example.com"},
        ],
        "products": [{"id": 9, "sku": "SKU-9"}],
    },
    [
        DeclaredFK(
            src_collection="orders",
            src_columns=["customer_id"],
            dst_collection="customers",
            dst_columns=["id"],
        )
    ],
)


def _column(collection_id: str, column_name: str) -> ColumnProfile:
    return ColumnProfile(
        collection_id=collection_id,
        column_name=column_name,
        type_class="text",
    )


def test_declared_fk_contract() -> None:
    check_link_matcher(
        DeclaredFkMatcher(_SOURCE),
        src=_column("orders", "customer_id"),
        dst=_column("customers", "id"),
        unrelated=_column("customers", "email"),
        link=Link(
            link_id="orders.customer_id",
            match_type="declared_fk",
            src_collection="orders",
            src_column="customer_id",
            dst_collection="customers",
            dst_column="id",
        ),
        values=["1", "2"],
        missing_value="99",
        expected_value="1",
        expected_pk={"id": 1},
    )


def test_exact_contract() -> None:
    check_link_matcher(
        ExactMatcher(_SOURCE),
        src=_column("orders", "email"),
        dst=_column("customers", "email"),
        unrelated=_column("products", "sku"),
        link=Link(
            link_id="orders.email",
            match_type="exact",
            src_collection="orders",
            src_column="email",
            dst_collection="customers",
            dst_column="email",
        ),
        values=["a@example.com", "b@example.com"],
        missing_value="missing@example.com",
        expected_value="a@example.com",
        expected_pk={"id": 1},
    )


def test_normalized_contract() -> None:
    source = MemoryTabularSource(
        {
            "orders": [
                {"id": 1, "email": "Ada@Example.com"},
                {"id": 2, "email": "Bob@Example.com"},
            ],
            "customers": [
                {"id": 1, "email": "ada@example.com"},
                {"id": 2, "email": "bob@example.com"},
            ],
            "products": [{"id": 9, "sku": "SKU-9"}],
        }
    )
    check_link_matcher(
        NormalizedMatcher(source),
        src=_column("orders", "email"),
        dst=_column("customers", "email"),
        unrelated=_column("products", "sku"),
        link=Link(
            link_id="orders.email",
            match_type="normalized",
            src_collection="orders",
            src_column="email",
            dst_collection="customers",
            dst_column="email",
            normalize_sql="fold",
        ),
        values=["Ada@Example.com", "Bob@Example.com"],
        missing_value="missing@example.com",
        expected_value="Ada@Example.com",
        expected_pk={"id": 1},
    )


def test_fuzzy_contract() -> None:
    source = MemoryTabularSource(
        {
            "orders": [
                {"id": 1, "name": "Ada Lovelace"},
                {"id": 2, "name": "Grace Hopper"},
            ],
            "customers": [
                {"id": 1, "name": "Ada Lovlace"},
                {"id": 2, "name": "Grace Hoppr"},
            ],
            "products": [{"id": 9, "sku": "SKU-9"}],
        }
    )
    check_link_matcher(
        FuzzyMatcher(source),
        src=_column("orders", "name"),
        dst=_column("customers", "name"),
        unrelated=_column("products", "sku"),
        link=Link(
            link_id="orders.name",
            match_type="fuzzy",
            src_collection="orders",
            src_column="name",
            dst_collection="customers",
            dst_column="name",
        ),
        values=["Ada Lovelace", "Grace Hopper"],
        missing_value="zzzzzzzzzz",
        expected_value="Ada Lovelace",
        expected_pk={"id": 1},
    )


def test_column_documents_contract() -> None:
    source = MemoryTabularSource(
        {
            "orders": [
                {"id": 1, "code": "ACME-1"},
                {"id": 2, "code": "ACME-2"},
            ]
        }
    )
    passages = [
        Passage("s3://docs/", {"chunk_id": 1}, "Invoice for ACME-1 shipped today"),
        Passage("s3://docs/", {"chunk_id": 2}, "Quote ACME-2 is attached"),
        Passage("s3://other/", {"chunk_id": 9}, "Unrelated handbook"),
    ]
    check_link_matcher(
        DocumentMatcher(source, passages),
        src=_column("orders", "code"),
        dst=CollectionProfile(collection_id="s3://docs/"),
        unrelated=CollectionProfile(collection_id="s3://other/"),
        link=Link(
            link_id="orders.code",
            match_type="column_documents",
            src_collection="orders",
            src_column="code",
            dst_collection="s3://docs/",
            dst_column=None,
        ),
        values=["ACME-1", "ACME-2"],
        missing_value="MISSING",
        expected_value="ACME-1",
        expected_pk={"chunk_id": 1},
    )

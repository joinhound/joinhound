# SPDX-License-Identifier: Apache-2.0

"""Behavior of the equality matchers beyond the shared contract."""

from joinhound.core.models import (
    CollectionProfile,
    ColumnProfile,
    DeclaredFK,
    Link,
    ProfileContext,
    QueryContext,
)
from joinhound.matchers import DeclaredFkMatcher, ExactMatcher
from joinhound.testing.memory import MemoryTabularSource


def _column(collection_id: str, column_name: str) -> ColumnProfile:
    return ColumnProfile(
        collection_id=collection_id,
        column_name=column_name,
        type_class="text",
    )


def test_exact_rejects_low_containment() -> None:
    orders = [{"id": index, "code": code} for index, code in enumerate(["a", "b", "c", "d"])]
    source = MemoryTabularSource(
        {
            "orders": orders,
            "products": [{"id": 1, "code": "a"}],
        }
    )
    matcher = ExactMatcher(source)

    assert (
        matcher.discover(
            _column("orders", "code"),
            _column("products", "code"),
            ProfileContext(),
        )
        is None
    )


def test_exact_confidence_is_containment() -> None:
    source = MemoryTabularSource(
        {
            "orders": [{"id": 1, "code": "a"}, {"id": 2, "code": "b"}],
            "products": [{"id": 1, "code": "a"}, {"id": 2, "code": "b"}],
        }
    )

    candidate = ExactMatcher(source).discover(
        _column("orders", "code"),
        _column("products", "code"),
        ProfileContext(),
    )

    assert candidate is not None
    assert candidate.confidence == 1.0


def test_declared_fk_skips_composite_keys_and_the_reverse_direction() -> None:
    rows = {
        "orders": [{"id": 1, "customer_id": 1}],
        "customers": [{"id": 1, "email": "a@example.com"}],
    }
    single = DeclaredFK(
        src_collection="orders",
        src_columns=["customer_id"],
        dst_collection="customers",
        dst_columns=["id"],
    )
    composite = DeclaredFK(
        src_collection="orders",
        src_columns=["customer_id", "email"],
        dst_collection="customers",
        dst_columns=["id", "email"],
    )
    profile = ProfileContext()
    forward = (_column("orders", "customer_id"), _column("customers", "id"))
    reverse = (_column("customers", "id"), _column("orders", "customer_id"))
    composite_matcher = DeclaredFkMatcher(MemoryTabularSource(rows, [composite]))
    single_matcher = DeclaredFkMatcher(MemoryTabularSource(rows, [single]))

    assert composite_matcher.discover(*forward, profile) is None
    assert single_matcher.discover(*forward, profile) is not None
    assert single_matcher.discover(*reverse, profile) is None
    documents = CollectionProfile(collection_id="docs")
    assert single_matcher.discover(forward[0], documents, profile) is None


def test_resolve_ignores_a_different_match_type() -> None:
    source = MemoryTabularSource({"customers": [{"id": 1, "email": "a@example.com"}]})
    link = Link(
        link_id="orders.email",
        match_type="fuzzy",
        src_collection="orders",
        src_column="email",
        dst_collection="customers",
        dst_column="email",
    )

    assert ExactMatcher(source).resolve(link, ["a@example.com"], QueryContext()) == []

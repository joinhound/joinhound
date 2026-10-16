# SPDX-License-Identifier: Apache-2.0

"""Relationship drafts from an in-memory source."""

from joinhound.core.config import ProfilerConfig
from joinhound.core.models import DeclaredFK
from joinhound.index.links import link_status
from joinhound.matchers import DeclaredFkMatcher, ExactMatcher
from joinhound.profiler.profile import link_id, propose_links
from joinhound.testing.memory import MemoryTabularSource

_ROWS = 20


def test_link_id_uses_schema_and_table() -> None:
    assert (
        link_id(
            "pg://shop/public.orders",
            "customer_id",
            "pg://shop/public.customers",
            "id",
        )
        == "public.orders.customer_id__public.customers.id"
    )


def test_auto_approve_promotes_only_proposals() -> None:
    assert link_status("proposed", 0.9, 0.9) == "approved"
    assert link_status("proposed", 0.89, 0.9) == "proposed"
    assert link_status("approved", 0.2, 0.9) == "approved"
    assert link_status("rejected", 1.0, 0.9) == "rejected"
    assert link_status("proposed", 1.0, None) == "proposed"


def test_declared_foreign_key_is_approved_and_not_repeated_as_exact() -> None:
    source = MemoryTabularSource(_tables(), [_foreign_key(), _composite_key()])
    _profiles, drafts = propose_links(
        source,
        ProfilerConfig(),
        {"declared_fk": DeclaredFkMatcher(source), "exact": ExactMatcher(source)},
    )

    declared = [
        draft
        for draft in drafts
        if draft.match_type == "declared_fk" and draft.src_column == "customer_id"
    ]
    assert len(declared) == 1
    assert declared[0].status == "approved"
    assert declared[0].origin == "catalog_fk"
    assert declared[0].confidence == 1.0
    assert declared[0].cardinality == "N:1"
    assert declared[0].evidence["catalog"] is True
    assert not any(
        draft.match_type == "exact"
        and draft.src_collection == "orders"
        and draft.src_column == "customer_id"
        and draft.dst_collection == "customers"
        and draft.dst_column == "id"
        for draft in drafts
    )
    emails = [
        draft for draft in drafts if draft.src_column == "email" and draft.match_type == "exact"
    ]
    assert emails
    assert emails[0].status == "proposed"
    assert emails[0].origin == "discovered"
    assert emails[0].evidence["containment"] == 1.0
    assert len({draft.link_id for draft in drafts}) == len(drafts)


def _tables() -> dict[str, list[dict[str, object]]]:
    customers = [
        {"id": number, "email": f"user{number}@example.com"} for number in range(1, _ROWS + 1)
    ]
    orders = [
        {"id": number, "customer_id": number, "email": f"user{number}@example.com"}
        for number in range(1, _ROWS + 1)
    ]
    return {"customers": customers, "orders": orders}


def _foreign_key() -> DeclaredFK:
    return DeclaredFK(
        src_collection="orders",
        src_columns=["customer_id"],
        dst_collection="customers",
        dst_columns=["id"],
    )


def _composite_key() -> DeclaredFK:
    return DeclaredFK(
        src_collection="orders",
        src_columns=["customer_id", "email"],
        dst_collection="customers",
        dst_columns=["id", "email"],
    )

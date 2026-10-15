# SPDX-License-Identifier: Apache-2.0

"""Tests for column exclusion and the integer-id rule."""

from joinhound.core.models import ColumnProfile
from joinhound.profiler.candidates import (
    ProfiledColumn,
    candidate_pairs,
    exclusion_reason,
    names_related,
)
from joinhound.profiler.fingerprint import minhash_bytes


def test_year_column_is_excluded() -> None:
    years = _column(
        "pg://shop/public.film",
        "release_year",
        "int",
        [str(year) for year in range(1990, 2020)],
    )
    other = _ids("pg://shop/public.orders", "id")

    assert exclusion_reason(years) == "year"
    assert candidate_pairs([years, other]) == []


def test_boolean_column_is_excluded() -> None:
    flag = _column("pg://shop/public.customer", "active", "bool", ["true", "false"])

    assert exclusion_reason(flag) == "bool"


def test_overlapping_ids_of_unrelated_tables_are_rejected() -> None:
    orders = _ids("pg://shop/public.orders", "id")
    products = _ids("pg://shop/public.products", "id")

    assert candidate_pairs([orders, products]) == []


def test_customer_id_matches_customers_id() -> None:
    foreign_key = _column(
        "pg://shop/public.orders",
        "customer_id",
        "int",
        [str(value) for value in range(1, 51)],
        uniqueness=0.4,
        n_distinct=50,
    )
    primary_key = _ids("pg://shop/public.customers", "id")

    pairs = candidate_pairs([foreign_key, primary_key])

    assert names_related(foreign_key.profile, primary_key.profile)
    assert not names_related(primary_key.profile, _ids("pg://shop/public.products", "id").profile)
    assert any(
        pair.source.column_name == "customer_id" and pair.destination.column_name == "id"
        for pair in pairs
    )


def _ids(collection_id: str, column_name: str) -> ProfiledColumn:
    return _column(
        collection_id,
        column_name,
        "int",
        [str(value) for value in range(1, 101)],
        uniqueness=1.0,
        n_distinct=100,
    )


def _column(
    collection_id: str,
    column_name: str,
    type_class: str,
    values: list[str],
    *,
    uniqueness: float | None = None,
    n_distinct: float | None = None,
) -> ProfiledColumn:
    profile = ColumnProfile(
        collection_id=collection_id,
        column_name=column_name,
        type_class=type_class,
        n_distinct=float(len(set(values))) if n_distinct is None else n_distinct,
        uniqueness=uniqueness,
        pattern="9" if type_class == "int" else None,
        minhash=minhash_bytes(values),
    )
    return ProfiledColumn(profile=profile, values=tuple(values))

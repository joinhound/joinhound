# SPDX-License-Identifier: Apache-2.0

"""Round-trip tests for provenance URIs."""

import pytest

from joinhound.core.uri import MssqlUri, PgUri, S3Uri, UriError, build_uri, parse_uri


def test_postgres_uri_round_trip_with_composite_key() -> None:
    original = PgUri(
        source="main",
        schema="public",
        table="orders",
        pk={"id": 901, "tenant": "acme"},
        column="code",
    )

    parsed = parse_uri(build_uri(original))

    assert parsed == original
    assert (
        build_uri(parsed)
        == "pg://main/public.orders#pk=%7B%22id%22%3A901%2C%22tenant%22%3A%22acme%22%7D&col=code"
    )


def test_unstable_ctid_uri_round_trip() -> None:
    original = PgUri(
        source="main",
        schema="public",
        table="events",
        pk={"ctid": "(0,1)"},
        unstable=True,
        row_hash="abc123",
    )

    assert parse_uri(build_uri(original)) == original


def test_mssql_uri_round_trip() -> None:
    original = MssqlUri(source="warehouse", schema="dbo", table="customers", pk={"id": 1})

    parsed = parse_uri(build_uri(original))

    assert parsed == original
    assert build_uri(parsed) == "mssql://warehouse/dbo.customers#pk=%7B%22id%22%3A1%7D"


def test_s3_passage_uri_round_trip() -> None:
    original = S3Uri(
        source="specs",
        key="2025/prd-901.pdf",
        page=3,
        bbox=(72.0, 140.0, 310.0, 162.0),
    )

    parsed = parse_uri(build_uri(original))

    assert parsed == original


def test_invalid_postgres_uri_is_rejected() -> None:
    with pytest.raises(UriError):
        parse_uri("pg://main/orders")

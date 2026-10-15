# SPDX-License-Identifier: Apache-2.0

"""Tests for kg migration URL handling."""

import pytest

from joinhound.index.schema import migrations_directory, yoyo_uri


def test_libpq_url_uses_psycopg3() -> None:
    dsn = "postgresql://joinhound:joinhound@localhost:55432/joinhound"
    assert yoyo_uri(dsn) == "postgresql+psycopg://joinhound:joinhound@localhost:55432/joinhound"


def test_postgres_scheme_uses_psycopg3() -> None:
    assert yoyo_uri("postgres://user@localhost/db").startswith("postgresql+psycopg://")


def test_psycopg_url_is_unchanged() -> None:
    dsn = "postgresql+psycopg://user@localhost/db"
    assert yoyo_uri(dsn) == dsn


def test_unsupported_scheme_is_rejected() -> None:
    with pytest.raises(ValueError, match="mysql"):
        yoyo_uri("mysql://user@localhost/db")


def test_migrations_directory_contains_kg_schema() -> None:
    assert (migrations_directory() / "0001.kg.sql").is_file()

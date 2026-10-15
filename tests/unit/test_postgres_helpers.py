# SPDX-License-Identifier: Apache-2.0

"""Unit tests for PostgreSQL source helpers."""

from joinhound.connectors.postgres.source import distinct_estimate, type_class


def test_type_class_maps_catalog_names() -> None:
    assert type_class("varchar") == "text"
    assert type_class("int4") == "int"
    assert type_class("timestamptz") == "date"
    assert type_class("uuid") == "uuid"
    assert type_class("bool") == "bool"
    assert type_class("numeric") == "numeric"


def test_unknown_type_class_is_text() -> None:
    assert type_class("jsonb") == "text"


def test_negative_n_distinct_uses_row_estimate() -> None:
    assert distinct_estimate(-0.5, 100) == 50
    assert distinct_estimate(3, 100) == 3
    assert distinct_estimate(None, 100) is None
    assert distinct_estimate(-0.5, 0) is None

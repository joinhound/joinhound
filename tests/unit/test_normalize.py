# SPDX-License-Identifier: Apache-2.0

"""Normalization expressions."""

from joinhound.index.normalize import apply, names, sql_expression


def test_fold_trims_and_lowers() -> None:
    assert apply("fold", "  Ada@Example.com ") == "ada@example.com"
    assert "fold" in names()


def test_compact_drops_punctuation_and_spaces() -> None:
    assert apply("compact", "PRD-901") == "prd901"


def test_strip_zeros_keeps_a_zero() -> None:
    assert apply("strip_zeros", "007") == "7"
    assert apply("strip_zeros", "0") == "0"


def test_sql_quotes_the_column() -> None:
    assert sql_expression("fold", 'odd"name') == 'lower(trim("odd""name"::text))'

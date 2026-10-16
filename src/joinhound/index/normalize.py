# SPDX-License-Identifier: Apache-2.0

"""Normalization expressions shared by indexing and later matchers."""

from __future__ import annotations


def names() -> tuple[str, ...]:
    """Return the expression names in a stable order."""
    return ("lower", "trim", "compact", "strip_zeros", "fold")


def apply(name: str, value: str) -> str:
    """Normalize one value in Python. ``fold`` is trim followed by lower."""
    if name == "lower":
        return value.casefold()
    if name == "trim":
        return value.strip()
    if name == "compact":
        return "".join(character for character in value.casefold() if character.isalnum())
    if name == "strip_zeros":
        stripped = value.strip().lstrip("0")
        return stripped or "0"
    if name == "fold":
        return value.strip().casefold()
    raise ValueError(f"Unknown normalization {name}")


def sql_expression(name: str, column: str) -> str:
    """Return a PostgreSQL expression for one column. The name is quoted."""
    if name not in names():
        raise ValueError(f"Unknown normalization {name}")
    ident = '"' + column.replace('"', '""') + '"::text'
    if name == "lower":
        return f"lower({ident})"
    if name == "trim":
        return f"trim({ident})"
    if name == "compact":
        return f"lower(regexp_replace({ident}, '[^[:alnum:]]', '', 'g'))"
    if name == "strip_zeros":
        return f"regexp_replace(trim({ident}), '^0+', '')"
    return f"lower(trim({ident}))"

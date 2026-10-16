# SPDX-License-Identifier: Apache-2.0

"""Deterministic dirty copies of Pagila-shaped columns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_ROWS = 40


@dataclass(frozen=True)
class DirtyColumn:
    """One clean column and the dirty copy that should still match it."""

    name: str
    match_type: str
    expression: str | None
    src_collection: str
    src_column: str
    dst_collection: str
    dst_column: str
    pairs: tuple[tuple[int, str, str], ...]


def generate_dirty_pagila() -> tuple[dict[str, list[dict[str, object]]], tuple[DirtyColumn, ...]]:
    """Return tables and the three gold column pairs.

    Every email changes case, every phone changes punctuation, and every film
    code gains a prefix. Every tenth value also drops one character.
    """
    emails = _column("email", "normalized", "fold", _email, _email_dirty)
    phones = _column("phone", "normalized", "compact", _phone, _phone_dirty)
    codes = _column("code", "fuzzy", None, _code, _code_dirty)
    tables = {
        "customer": [_clean("customer", row) for row in range(_ROWS)],
        "address": [_clean("address", row) for row in range(_ROWS)],
        "film": [_clean("film", row) for row in range(_ROWS)],
        "intake": [_dirty(row) for row in range(_ROWS)],
    }
    return tables, (emails, phones, codes)


def _column(
    name: str,
    match_type: str,
    expression: str | None,
    clean: Callable[[int], str],
    dirty: Callable[[int], str],
) -> DirtyColumn:
    destination = {"email": "customer", "phone": "address", "code": "film"}[name]
    return DirtyColumn(
        name=name,
        match_type=match_type,
        expression=expression,
        src_collection="intake",
        src_column=name,
        dst_collection=destination,
        dst_column=name,
        pairs=tuple((row, dirty(row), clean(row)) for row in range(_ROWS)),
    )


def _clean(table: str, row: int) -> dict[str, object]:
    if table == "customer":
        return {"id": row, "email": _email(row)}
    if table == "address":
        return {"id": row, "phone": _phone(row)}
    return {"id": row, "code": _code(row)}


def _dirty(row: int) -> dict[str, object]:
    return {
        "id": row,
        "email": _email_dirty(row),
        "phone": _phone_dirty(row),
        "code": _code_dirty(row),
    }


def _email(row: int) -> str:
    return f"user{row:02d}@pagila.example"


def _phone(row: int) -> str:
    return f"555-01{row:02d}"


def _code(row: int) -> str:
    return f"F-{1000 + row}"


def _email_dirty(row: int) -> str:
    value = _email(row).upper()
    return _typo(value, row)


def _phone_dirty(row: int) -> str:
    digits = _phone(row).replace("-", "")
    value = f"({digits[:3]}) {digits[3:]}"
    return _typo(value, row)


def _code_dirty(row: int) -> str:
    return _typo(f"CODE-{_code(row)}", row)


def _typo(value: str, row: int) -> str:
    if row % 10 != 0 or len(value) < 4:
        return value
    index = len(value) // 2
    return value[:index] + value[index + 1 :]

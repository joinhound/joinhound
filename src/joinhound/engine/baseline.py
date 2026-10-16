# SPDX-License-Identifier: Apache-2.0

"""Compare an answer's cited rows with a gold set and with rows a tool returned."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from joinhound.core.uri import PgUri, build_uri
from joinhound.engine.evaluate import record_key

_TABLE = re.compile(r"\b(?:from|join)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.IGNORECASE)
_STOP = set('"\n\t ,)')


def cited_keys(text: str) -> set[tuple[str, str, str]]:
    """Return the row keys of provenance URIs written in an answer or a tool result."""
    keys: set[tuple[str, str, str]] = set()
    start = 0
    while True:
        index = text.find("pg://", start)
        if index < 0:
            break
        candidate = _uri_at(text, index)
        if candidate is None:
            start = index + 5
            continue
        try:
            keys.add(record_key(candidate))
        except ValueError:
            start = index + 5
            continue
        start = index + len(candidate)
    return keys


def _uri_at(text: str, index: int) -> str | None:
    rest = text[index:]
    marker = rest.find("#pk=")
    if marker < 0:
        return None
    if rest[marker + 4 : marker + 5] == "{":
        end = rest.find("}", marker)
        if end < 0:
            return None
        return rest[: end + 1]
    end = len(rest)
    for position, character in enumerate(rest):
        if character in _STOP:
            end = position
            break
    return rest[:end].rstrip(".,`")


def answer_recall(answer: str, gold: Sequence[str]) -> float:
    """Return the share of gold rows cited in the answer. An empty gold set scores 0."""
    gold_keys = {record_key(uri) for uri in gold}
    if not gold_keys:
        return 0.0
    return len(cited_keys(answer) & gold_keys) / len(gold_keys)


def answer_confirmed(answer: str, observed: set[tuple[str, str, str]]) -> bool:
    """A confirmed answer cites at least one row that a tool actually returned."""
    return bool(cited_keys(answer) & observed)


def tables_in_sql(sql: str) -> list[str]:
    """Return table names named after FROM or JOIN, without the schema."""
    return [match.group(1) for match in _TABLE.finditer(sql)]


def uris_from_rows(
    rows: Sequence[Mapping[str, object]],
    primary_keys: Mapping[str, Sequence[str]],
    tables: Sequence[str],
) -> list[str]:
    """Build a row URI when a result contains every primary-key column of a named table."""
    found: list[str] = []
    for row in rows:
        for table in tables:
            columns = primary_keys.get(table)
            if columns is None:
                continue
            if any(column not in row or row[column] is None for column in columns):
                continue
            found.append(
                build_uri(
                    PgUri(
                        source="pagila",
                        schema="public",
                        table=table,
                        pk={column: row[column] for column in columns},
                    )
                )
            )
    return found

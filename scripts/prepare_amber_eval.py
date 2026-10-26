# SPDX-License-Identifier: Apache-2.0

"""Download the CC0 AmbER tuples and prepare an ambiguous-entity eval."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import psycopg

from joinhound.amber_eval import (
    AMBER_SHA256,
    AMBER_URL,
    DEFAULT_SETS,
    AmberEntity,
    cases,
    load_sets,
    sha256,
    write_bundle,
)

_SCHEMA = """
DROP TABLE IF EXISTS amber_fact_aliases;
DROP TABLE IF EXISTS amber_facts;
DROP TABLE IF EXISTS amber_entities;

CREATE TABLE amber_entities (
    qid text PRIMARY KEY,
    ambiguous_name text NOT NULL,
    is_head boolean NOT NULL,
    popularity double precision NOT NULL
);

CREATE TABLE amber_facts (
    id integer PRIMARY KEY,
    qid text NOT NULL,
    property_id text NOT NULL,
    property_name text NOT NULL,
    answer text NOT NULL,
    UNIQUE (qid, property_id)
);

CREATE TABLE amber_fact_aliases (
    id integer PRIMARY KEY,
    fact_id integer NOT NULL,
    alias text NOT NULL,
    UNIQUE (fact_id, alias)
);
"""


def main() -> None:
    """Prepare a Postgres database and local dossier files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="Empty evaluation database")
    parser.add_argument("--cache", type=Path, default=Path("cache/amber-eval"))
    parser.add_argument("--sets", type=int, default=DEFAULT_SETS)
    parser.add_argument(
        "--distort",
        action="store_true",
        help="Write dossier clues that are not exact aliases",
    )
    args = parser.parse_args()

    args.cache.mkdir(parents=True, exist_ok=True)
    source = args.cache / "amber_set_tuples.jsonl"
    _download(source)
    selected_sets = load_sets(source, args.sets)
    fact_ids = _load(args.dsn, selected_sets)
    bundle = args.cache / ("bundle-fuzzy" if args.distort else "bundle")
    if bundle.exists():
        shutil.rmtree(bundle)
    write_bundle(bundle, cases(selected_sets), fact_ids, distort=args.distort)
    print(
        f"Prepared {args.sets} ambiguous names, {args.sets * 2} dossiers, "
        f"and {args.sets * 2} questions in {bundle}"
    )


def _download(path: Path) -> None:
    if path.exists() and sha256(path) == AMBER_SHA256:
        return
    subprocess.run(["curl", "-fsSL", AMBER_URL, "-o", str(path)], check=True)
    actual = sha256(path)
    if actual != AMBER_SHA256:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"AmbER checksum is {actual}, expected {AMBER_SHA256}")


def _load(dsn: str, selected_sets: list[list[AmberEntity]]) -> dict[tuple[str, str], int]:
    entities = {entity.qid: entity for selected_set in selected_sets for entity in selected_set}
    fact_ids: dict[tuple[str, str], int] = {}
    fact_rows: list[tuple[object, ...]] = []
    alias_rows: list[tuple[object, ...]] = []
    for entity in sorted(entities.values(), key=lambda item: item.qid):
        for fact in sorted(entity.facts, key=lambda item: item.property_id):
            fact_id = len(fact_rows) + 1
            fact_ids[(entity.qid, fact.property_id)] = fact_id
            fact_rows.append(
                (
                    fact_id,
                    entity.qid,
                    fact.property_id,
                    fact.property_name,
                    fact.answer,
                )
            )
            for alias in fact.aliases:
                alias_rows.append((len(alias_rows) + 1, fact_id, alias))
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(_SCHEMA)
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO amber_entities VALUES (%s, %s, %s, %s)",
                [
                    (entity.qid, entity.name, entity.is_head, entity.popularity)
                    for entity in sorted(entities.values(), key=lambda item: item.qid)
                ],
            )
            cursor.executemany(
                "INSERT INTO amber_facts VALUES (%s, %s, %s, %s, %s)",
                fact_rows,
            )
            cursor.executemany(
                "INSERT INTO amber_fact_aliases VALUES (%s, %s, %s)",
                alias_rows,
            )
    return fact_ids


if __name__ == "__main__":
    main()

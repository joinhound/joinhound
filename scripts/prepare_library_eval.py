# SPDX-License-Identifier: Apache-2.0

"""Download the CC0 library database and build the large evaluation bundle."""

from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from joinhound.library_eval import (
    DATASET_SHA256,
    DATASET_URL,
    DEFAULT_DOCUMENTS,
    DEFAULT_QUESTIONS,
    LibraryCase,
    questions,
    sha256,
    write_bundle,
)

_CREATE_CASES = """
CREATE TABLE eval_cases AS
SELECT
  row_number() OVER (ORDER BY loans.id)::integer AS id,
  'CASE-' || lpad(loans.id::text, 8, '0') AS case_ref,
  loans.id AS loan_id
FROM loans
ORDER BY loans.id
LIMIT %s;
"""

_CASE_KEYS = (
    "ALTER TABLE eval_cases ADD PRIMARY KEY (id)",
    "ALTER TABLE eval_cases ADD CONSTRAINT uq_eval_cases_ref UNIQUE (case_ref)",
    "ALTER TABLE eval_cases ADD CONSTRAINT uq_eval_cases_loan UNIQUE (loan_id)",
    (
        "ALTER TABLE eval_cases ADD CONSTRAINT fk_eval_cases_loan "
        "FOREIGN KEY (loan_id) REFERENCES loans (id)"
    ),
)

_CASE_ROWS = """
SELECT
  cases.id AS case_id,
  cases.case_ref,
  loans.id AS loan_id,
  memberships.id AS membership_id,
  users.id AS user_id,
  users.first_name || ' ' || users.last_name AS user_name,
  copies.id AS copy_id,
  books.id AS book_id,
  books.title AS book_title,
  libraries.id AS library_id,
  libraries.name AS library_name,
  memberships.card_number
FROM eval_cases AS cases
JOIN loans ON loans.id = cases.loan_id
JOIN memberships ON memberships.id = loans.membership_id
JOIN users ON users.id = memberships.user_id
JOIN copies ON copies.id = loans.copy_id
JOIN books ON books.id = copies.book_id
JOIN libraries ON libraries.id = copies.library_id
ORDER BY cases.id
"""


def main() -> None:
    """Prepare an empty Postgres database and a local file bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="Empty evaluation database")
    parser.add_argument("--cache", type=Path, default=Path("cache/library-eval"))
    parser.add_argument("--documents", type=int, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--questions", type=int, default=DEFAULT_QUESTIONS)
    parser.add_argument(
        "--skip-load",
        action="store_true",
        help="Keep the existing library tables and only rebuild eval_cases and files",
    )
    args = parser.parse_args()
    if args.documents <= 0:
        parser.error("--documents must be positive")

    args.cache.mkdir(parents=True, exist_ok=True)
    archive = args.cache / "postgres.sql.gz"
    if not args.skip_load:
        _download(archive)
        _load(args.dsn, archive)
    cases = _cases(args.dsn, args.documents)
    bundle = args.cache / "bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    write_bundle(bundle, cases, questions(cases, args.questions))
    print(
        f"Prepared {len(cases):,} files and {args.questions:,} questions in {bundle} "
        f"from {DATASET_URL}"
    )


def _download(path: Path) -> None:
    if path.exists() and sha256(path) == DATASET_SHA256:
        return
    subprocess.run(["curl", "-fsSL", DATASET_URL, "-o", str(path)], check=True)
    actual = sha256(path)
    if actual != DATASET_SHA256:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"Dataset checksum is {actual}, expected {DATASET_SHA256}")


def _load(dsn: str, archive: Path) -> None:
    with gzip.open(archive, "rb") as source:
        process = subprocess.run(
            ["psql", dsn, "--set", "ON_ERROR_STOP=1"],
            stdin=source,
            check=False,
        )
    if process.returncode:
        raise RuntimeError("psql could not load the library dataset; use an empty database")


def _cases(dsn: str, limit: int) -> list[LibraryCase]:
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        connection.execute("DROP TABLE IF EXISTS eval_cases")
        connection.execute(_CREATE_CASES, (limit,))
        for statement in _CASE_KEYS:
            connection.execute(statement)
        rows = connection.execute(_CASE_ROWS).fetchall()
    if len(rows) != limit:
        raise RuntimeError(f"The database yielded {len(rows)} cases, expected {limit}")
    return [LibraryCase(**row) for row in rows]


if __name__ == "__main__":
    main()

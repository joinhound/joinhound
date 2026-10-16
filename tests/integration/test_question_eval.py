# SPDX-License-Identifier: Apache-2.0

"""get_context recall on the Pagila question set stays near the recorded baseline."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import PostgresSourceConfig
from joinhound.core.models import LinkDraft
from joinhound.engine.questions import load_questions, score_questions
from joinhound.matchers import DeclaredFkMatcher
from joinhound.profiler.profile import link_id

_PAGILA_REF = "ce6e114236bb828e5ec0dc835f65f1bf1b9179f5"
_ROOT = Path(__file__).resolve().parents[2]
_QUESTIONS = _ROOT / "tests" / "eval" / "gold" / "pagila_questions.json"
# Macro recall measured on the pinned Pagila revision. A drop of more than 0.02 fails.
_RECALL_BASELINE = 0.7037


@pytest.fixture(scope="module")
def pagila_dsn() -> Iterator[str]:
    with PostgresContainer(
        "pgvector/pgvector:pg18",
        username="postgres",
        password="postgres",
        dbname="pagila",
        driver=None,
    ) as postgres:
        _load_pagila(postgres)
        yield postgres.get_connection_url(driver=None)


def test_question_recall_stays_within_the_regression_band(pagila_dsn: str) -> None:
    questions = load_questions(_QUESTIONS)
    with PostgresSource(
        "pagila",
        PostgresSourceConfig(
            type="postgres",
            dsn=pagila_dsn,
            schemas=["public"],
            statement_timeout_ms=30_000,
        ),
    ) as source:
        report = score_questions(
            questions,
            source,
            _declared(source),
            {"declared_fk": DeclaredFkMatcher(source)},
        )

    assert report.recall >= _RECALL_BASELINE - 0.02


def _declared(source: PostgresSource) -> list[LinkDraft]:
    drafts: list[LinkDraft] = []
    for foreign_key in source.declared_links():
        if len(foreign_key.src_columns) != 1 or len(foreign_key.dst_columns) != 1:
            continue
        src_column = foreign_key.src_columns[0]
        dst_column = foreign_key.dst_columns[0]
        drafts.append(
            LinkDraft(
                link_id=link_id(
                    foreign_key.src_collection,
                    src_column,
                    foreign_key.dst_collection,
                    dst_column,
                ),
                src_collection=foreign_key.src_collection,
                src_column=src_column,
                dst_collection=foreign_key.dst_collection,
                dst_column=dst_column,
                match_type="declared_fk",
                origin="catalog_fk",
                confidence=1.0,
                status="approved",
                cardinality="N:1",
            )
        )
    return drafts


def _load_pagila(postgres: PostgresContainer) -> None:
    container_id = postgres.get_wrapped_container().id
    for name in ("pagila-schema.sql", "pagila-data.sql"):
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container_id,
                "psql",
                "--username",
                "postgres",
                "--dbname",
                "pagila",
                "--set",
                "ON_ERROR_STOP=1",
            ],
            input=_pagila_file(name).read_bytes(),
            check=True,
        )


def _pagila_file(name: str) -> Path:
    cache = _ROOT / "cache" / "pagila" / _PAGILA_REF
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    if path.is_file() and path.stat().st_size > 0:
        return path
    url = f"https://raw.githubusercontent.com/devrimgunduz/pagila/{_PAGILA_REF}/{name}"
    subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location", "--output", str(path), url],
        check=True,
    )
    return path

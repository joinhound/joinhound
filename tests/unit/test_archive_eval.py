# SPDX-License-Identifier: Apache-2.0

"""Highlight files answer questions that the catalog tables cannot."""

import json
from pathlib import Path

from joinhound.archive_eval import file_body, file_name, load_archive, measure
from joinhound.core.models import DeclaredFK
from joinhound.testing.memory import MemoryTabularSource

_ROOT = Path(__file__).resolve().parents[1] / "eval" / "archives"


def test_committed_highlight_files_match_the_dataset() -> None:
    payload = json.loads((_ROOT / "historical-document-archives.json").read_text(encoding="utf-8"))
    highlights = payload["document_highlights"]

    assert len(list((_ROOT / "files").glob("highlight-*.txt"))) == len(highlights)
    for row in highlights:
        body = (_ROOT / "files" / file_name(row["id"])).read_text(encoding="utf-8")
        assert body == file_body(row["document_id"], row["highlight_text"])


def test_files_raise_recall_where_the_catalog_cannot() -> None:
    dataset = load_archive(_ROOT / "historical-document-archives.json")
    source = MemoryTabularSource(
        dataset.rows,
        [
            DeclaredFK(
                src_collection="documents",
                src_columns=["author_id"],
                dst_collection="document_authors",
                dst_columns=["id"],
            ),
            DeclaredFK(
                src_collection="documents",
                src_columns=["document_era_id"],
                dst_collection="document_eras",
                dst_columns=["id"],
            ),
            DeclaredFK(
                src_collection="document_events",
                src_columns=["document_id"],
                dst_collection="documents",
                dst_columns=["id"],
            ),
        ],
    )

    gap = measure(source, dataset)

    assert gap.catalog_without == 1
    assert gap.catalog_with == 1
    assert gap.file_without == 0
    assert gap.file_with == 1
    assert gap.bridge_without == 0
    assert gap.bridge_with == 1

# SPDX-License-Identifier: Apache-2.0

"""Tests for foreign-key precision and recall."""

from joinhound.engine.evaluate import normalize_collection, precision_recall
from joinhound.index.links import ColumnLink


def test_empty_ontology_has_zero_recall() -> None:
    gold = [
        ColumnLink(
            src_collection="public.film",
            src_columns=("language_id",),
            dst_collection="public.language",
            dst_columns=("language_id",),
        )
    ]

    precision, recall = precision_recall([], gold)

    assert precision == 0
    assert recall == 0


def test_matching_link_scores_one() -> None:
    predicted = ColumnLink(
        src_collection="pg://pagila/public.film",
        src_columns=("language_id",),
        dst_collection="pg://pagila/public.language",
        dst_columns=("language_id",),
    )
    gold = ColumnLink(
        src_collection="public.film",
        src_columns=("language_id",),
        dst_collection="public.language",
        dst_columns=("language_id",),
    )

    assert precision_recall([predicted], [gold]) == (1, 1)


def test_collection_id_normalizes_to_schema_and_table() -> None:
    assert normalize_collection("pg://pagila/public.film") == "public.film"

# SPDX-License-Identifier: Apache-2.0

"""Tests for foreign-key and record-URI precision and recall."""

from joinhound.core.uri import PgUri, build_uri
from joinhound.engine.evaluate import (
    normalize_collection,
    overlap_scores,
    percentile,
    precision_recall,
)
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


def test_record_overlap_ignores_the_source_name() -> None:
    returned = build_uri(PgUri("other", "public", "film", {"film_id": 2}))
    gold = build_uri(PgUri("pagila", "public", "film", {"film_id": 2}))

    assert overlap_scores([returned], [gold]) == (1.0, 1.0)


def test_empty_context_has_zero_record_recall() -> None:
    gold = build_uri(PgUri("pagila", "public", "film", {"film_id": 2}))

    precision, recall = overlap_scores([], [gold])

    assert precision == 0
    assert recall == 0


def test_nearest_rank_percentile() -> None:
    assert percentile([10, 30, 20], 50) == 20
    assert percentile([10, 30, 20], 95) == 30
    assert percentile([], 50) == 0

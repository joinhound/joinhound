# SPDX-License-Identifier: Apache-2.0

"""Score stored column links against a gold set of foreign keys."""

from __future__ import annotations

from joinhound.index.links import ColumnLink


def precision_recall(
    predicted: list[ColumnLink],
    gold: list[ColumnLink],
) -> tuple[float, float]:
    """Return precision and recall. An empty prediction set has recall 0."""
    predicted_keys = {_key(link) for link in predicted}
    gold_keys = {_key(link) for link in gold}
    overlap = predicted_keys & gold_keys
    precision = len(overlap) / len(predicted_keys) if predicted_keys else 0.0
    recall = len(overlap) / len(gold_keys) if gold_keys else 0.0
    return precision, recall


def normalize_collection(value: str) -> str:
    """Reduce a collection id to schema.table."""
    if "://" in value:
        value = value.split("://", 1)[1]
        value = value.split("/", 1)[-1]
    return value


def _key(link: ColumnLink) -> tuple[str, tuple[str, ...], str, tuple[str, ...]]:
    return (
        normalize_collection(link.src_collection),
        link.src_columns,
        normalize_collection(link.dst_collection),
        link.dst_columns,
    )

# SPDX-License-Identifier: Apache-2.0

"""Score stored column links and context graphs against a gold set."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence

from joinhound.core.uri import PgUri, S3Uri, parse_uri
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


def overlap_scores(returned: Sequence[str], gold: Sequence[str]) -> tuple[float, float]:
    """Return precision and recall of record URIs. The source name is ignored."""
    returned_keys = {record_key(uri) for uri in returned}
    gold_keys = {record_key(uri) for uri in gold}
    hit = len(returned_keys & gold_keys)
    precision = hit / len(returned_keys) if returned_keys else 0.0
    recall = hit / len(gold_keys) if gold_keys else 0.0
    return precision, recall


def record_key(uri: str) -> tuple[str, str, str]:
    """Return the identity of a row or document. The source name and box are dropped."""
    parsed = parse_uri(uri)
    if isinstance(parsed, S3Uri):
        return ("s3", parsed.key, "")
    if not isinstance(parsed, PgUri):
        raise ValueError(f"Gold comparison supports row and document URIs only: {uri}")
    pk = json.dumps(dict(parsed.pk), sort_keys=True, separators=(",", ":"), default=str)
    return (parsed.schema, parsed.table, pk)


def percentile(values: Sequence[int], rank: float) -> int:
    """Return the nearest-rank percentile. An empty sample is 0."""
    if not values:
        return 0
    ordered = sorted(values)
    index = math.ceil(rank / 100 * len(ordered)) - 1
    return ordered[min(max(index, 0), len(ordered) - 1)]


def _key(link: ColumnLink) -> tuple[str, tuple[str, ...], str, tuple[str, ...]]:
    return (
        normalize_collection(link.src_collection),
        link.src_columns,
        normalize_collection(link.dst_collection),
        link.dst_columns,
    )

# SPDX-License-Identifier: Apache-2.0

"""Column fingerprints: type, statistics, value shape, and MinHash."""

from __future__ import annotations

from collections import Counter

import numpy as np
import psycopg
from datasketch import MinHash

from joinhound.core.models import ColumnProfile, ColumnStats
from joinhound.core.protocols import TabularSource

_MINHASH_PERMUTATIONS = 128
_MINHASH_SEED = 1


def profile_columns(source: TabularSource, sample_size: int = 10000) -> list[ColumnProfile]:
    """Fingerprint every column that can be sampled within the source timeout."""
    profiles: list[ColumnProfile] = []
    for collection in source.list_collections():
        try:
            stats = source.column_stats(collection.collection_id)
        except psycopg.Error:
            continue
        for stat in stats:
            try:
                rows = source.sample(collection.collection_id, [stat.column_name], sample_size)
            except psycopg.Error:
                break
            values = [row.get(stat.column_name) for row in rows]
            profiles.append(_profile(collection.collection_id, stat, values))
    return profiles


def value_pattern(value: str) -> str:
    """Collapse a value to letters, digits, and separators. `PRD-901` becomes `A-9`."""
    collapsed: list[str] = []
    for character in value:
        if character.isalpha():
            symbol = "A"
        elif character.isdigit():
            symbol = "9"
        else:
            symbol = character
        if not collapsed or collapsed[-1] != symbol:
            collapsed.append(symbol)
    return "".join(collapsed)


def minhash_bytes(values: list[str]) -> bytes:
    """Return the 128-permutation MinHash of the normalized values."""
    return _sketch(values).hashvalues.astype("<u4").tobytes()


def sketch_from_bytes(payload: bytes) -> MinHash:
    """Restore a MinHash written by minhash_bytes."""
    restored = np.frombuffer(payload, dtype="<u4").copy()
    if restored.size != _MINHASH_PERMUTATIONS:
        raise ValueError("MinHash must contain 128 permutations")
    sketch = MinHash(num_perm=_MINHASH_PERMUTATIONS, seed=_MINHASH_SEED)
    sketch.hashvalues = restored
    return sketch


def _sketch(values: list[str]) -> MinHash:
    sketch = MinHash(num_perm=_MINHASH_PERMUTATIONS, seed=_MINHASH_SEED)
    for value in values:
        sketch.update(_normalize(value).encode())
    return sketch


def _profile(
    collection_id: str,
    stat: ColumnStats,
    values: list[object | None],
) -> ColumnProfile:
    present = [str(value) for value in values if value is not None]
    distinct = set(present)
    null_count = len(values) - len(present)
    uniqueness = None if not present else len(distinct) / len(present)
    null_ratio = stat.null_ratio
    if null_ratio is None and values:
        null_ratio = null_count / len(values)
    n_distinct = stat.n_distinct if stat.n_distinct is not None else float(len(distinct))
    return ColumnProfile(
        collection_id=collection_id,
        column_name=stat.column_name,
        type_class=stat.type_class,
        n_distinct=n_distinct,
        null_ratio=null_ratio,
        uniqueness=uniqueness,
        pattern=_dominant_pattern(present),
        minhash=minhash_bytes(present),
    )


def _dominant_pattern(values: list[str]) -> str | None:
    if not values:
        return None
    counts = Counter(value_pattern(value) for value in values)
    return max(counts, key=lambda pattern: (counts[pattern], pattern))


def _normalize(value: str) -> str:
    return value.casefold().strip()

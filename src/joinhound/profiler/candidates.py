# SPDX-License-Identifier: Apache-2.0

"""Column filters and containment candidates for the profiler."""

from __future__ import annotations

import re
from dataclasses import dataclass

from datasketch import MinHashLSHEnsemble

from joinhound.core.config import ProfilerConfig
from joinhound.core.models import ColumnProfile
from joinhound.profiler.fingerprint import sketch_from_bytes

_GENERIC_TOKENS = frozenset({"code", "id", "key", "no", "num", "number", "pk"})
_TOKEN = re.compile(r"[a-z0-9]+")
_INTEGER = re.compile(r"-?\d+")


@dataclass(frozen=True)
class ProfiledColumn:
    """A column fingerprint plus the sampled values it was built from."""

    profile: ColumnProfile
    values: tuple[str, ...]


@dataclass(frozen=True)
class ColumnPair:
    """A directed candidate: values of the source may be contained in the destination."""

    source: ColumnProfile
    destination: ColumnProfile


def exclusion_reason(column: ProfiledColumn, config: ProfilerConfig | None = None) -> str | None:
    """Return why a column is skipped before pair search, or nothing if it can be paired."""
    settings = config or ProfilerConfig()
    profile = column.profile
    if profile.type_class == "bool":
        return "bool"
    if profile.n_distinct is not None:
        distinct = profile.n_distinct
    else:
        distinct = float(len(set(column.values)))
    if distinct < settings.min_distinct:
        return "low_cardinality"
    if profile.type_class == "numeric":
        return "numeric"
    if profile.type_class == "date":
        return "date"
    if _year_share(column.values, settings) > settings.year_share:
        return "year"
    if column.values and _mean_length(column.values) > settings.long_text_length:
        return "long_text"
    return None


def candidate_pairs(
    columns: list[ProfiledColumn],
    config: ProfilerConfig | None = None,
) -> list[ColumnPair]:
    """Return directed pairs that survive the containment search and the integer-id rule."""
    settings = config or ProfilerConfig()
    eligible = [column for column in columns if exclusion_reason(column, settings) is None]
    pairs = {**_containment_pairs(eligible, settings), **_pattern_pairs(eligible)}
    kept: list[ColumnPair] = []
    for source, destination in sorted(pairs.values(), key=_pair_key):
        if _integer_pair_allowed(source, destination, settings):
            kept.append(ColumnPair(source.profile, destination.profile))
    return kept


def names_related(source: ColumnProfile, destination: ColumnProfile) -> bool:
    """Return whether the source column name refers to the destination table or column."""
    source_tokens = _distinctive_tokens(source.column_name)
    if not source_tokens:
        source_tokens = _distinctive_tokens(_table_name(source.collection_id))
    destination_tokens = _distinctive_tokens(destination.column_name) + _distinctive_tokens(
        _table_name(destination.collection_id)
    )
    if not source_tokens or not destination_tokens:
        return False
    return all(
        any(_within_one_edit(token, other) for other in destination_tokens)
        for token in source_tokens
    )


def _containment_pairs(
    columns: list[ProfiledColumn],
    config: ProfilerConfig,
) -> dict[tuple[str, str, str, str], tuple[ProfiledColumn, ProfiledColumn]]:
    indexed = [column for column in columns if column.profile.minhash and _size(column) > 0]
    if len(indexed) < 2:
        return {}
    by_key = {_column_key(column): column for column in indexed}
    ensemble = MinHashLSHEnsemble(
        threshold=config.containment_threshold,
        num_perm=128,
    )
    ensemble.index(
        [
            (
                _column_key(column),
                sketch_from_bytes(column.profile.minhash or b""),
                _size(column),
            )
            for column in indexed
        ]
    )
    pairs: dict[tuple[str, str, str, str], tuple[ProfiledColumn, ProfiledColumn]] = {}
    for column in indexed:
        sketch = sketch_from_bytes(column.profile.minhash or b"")
        for key in ensemble.query(sketch, _size(column)):
            other = by_key.get(str(key))
            if other is None or other is column:
                continue
            pair = (column, other)
            pairs[_pair_key(pair)] = pair
    return pairs


def _pattern_pairs(
    columns: list[ProfiledColumn],
) -> dict[tuple[str, str, str, str], tuple[ProfiledColumn, ProfiledColumn]]:
    pairs: dict[tuple[str, str, str, str], tuple[ProfiledColumn, ProfiledColumn]] = {}
    for source in columns:
        pattern = source.profile.pattern
        if not pattern:
            continue
        for destination in columns:
            if source is destination:
                continue
            same_shape = destination.profile.pattern == pattern
            same_type = destination.profile.type_class == source.profile.type_class
            if same_shape and same_type:
                pair = (source, destination)
                pairs[_pair_key(pair)] = pair
    return pairs


def _integer_pair_allowed(
    source: ProfiledColumn,
    destination: ProfiledColumn,
    config: ProfilerConfig,
) -> bool:
    if source.profile.type_class != "int" or destination.profile.type_class != "int":
        return True
    uniqueness = destination.profile.uniqueness or 0
    if uniqueness < config.integer_uniqueness:
        return False
    if names_related(source.profile, destination.profile):
        return True
    contained = _containment(source.values, destination.values)
    distinct = source.profile.n_distinct or 0
    return contained >= config.integer_containment and distinct >= config.integer_min_distinct


def _year_share(values: tuple[str, ...], config: ProfilerConfig) -> float:
    if not values:
        return 0.0
    years = 0
    for value in values:
        if not _INTEGER.fullmatch(value):
            continue
        number = int(value)
        if config.year_min <= number <= config.year_max:
            years += 1
    return years / len(values)


def _mean_length(values: tuple[str, ...]) -> float:
    return sum(len(value) for value in values) / len(values)


def _containment(source: tuple[str, ...], destination: tuple[str, ...]) -> float:
    left = {_normalize(value) for value in source}
    if not left:
        return 0.0
    right = {_normalize(value) for value in destination}
    return len(left & right) / len(left)


def _size(column: ProfiledColumn) -> int:
    return len({_normalize(value) for value in column.values})


def _column_key(column: ProfiledColumn) -> str:
    return f"{column.profile.collection_id}\n{column.profile.column_name}"


def _pair_key(pair: tuple[ProfiledColumn, ProfiledColumn]) -> tuple[str, str, str, str]:
    source, destination = pair
    return (
        source.profile.collection_id,
        source.profile.column_name,
        destination.profile.collection_id,
        destination.profile.column_name,
    )


def _distinctive_tokens(name: str) -> list[str]:
    tokens = [_singular(token) for token in _TOKEN.findall(name.casefold())]
    return [token for token in tokens if token not in _GENERIC_TOKENS]


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _table_name(collection_id: str) -> str:
    location = collection_id.split("/")[-1]
    if "." not in location:
        return location
    return location.split(".", 1)[1]


def _within_one_edit(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(char != other for char, other in zip(left, right, strict=True)) <= 1
    if len(left) > len(right):
        left, right = right, left
    for index, character in enumerate(left):
        if character != right[index]:
            return left[index:] == right[index + 1 :]
    return True


def _normalize(value: str) -> str:
    return value.casefold().strip()

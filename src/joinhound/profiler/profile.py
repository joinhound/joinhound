# SPDX-License-Identifier: Apache-2.0

"""Turn source statistics into relationship drafts."""

from __future__ import annotations

from collections.abc import Mapping

from joinhound.core.config import ProfilerConfig
from joinhound.core.models import (
    Candidate,
    ColumnProfile,
    LinkDraft,
    ProfileContext,
)
from joinhound.core.protocols import LinkMatcher, TabularSource
from joinhound.profiler.candidates import ProfiledColumn, candidate_pairs
from joinhound.profiler.fingerprint import sampled_profiles


def link_id(
    src_collection: str,
    src_column: str,
    dst_collection: str,
    dst_column: str,
) -> str:
    """Identify a column pair. `pg://shop/public.orders` becomes `public.orders`."""
    return (
        f"{_collection_label(src_collection)}.{src_column}"
        f"__{_collection_label(dst_collection)}.{dst_column}"
    )


def propose_links(
    source: TabularSource,
    config: ProfilerConfig,
    matchers: Mapping[str, LinkMatcher],
) -> tuple[list[ColumnProfile], list[LinkDraft]]:
    """Return column fingerprints and the relationships to store."""
    sampled = sampled_profiles(source, config.sample_values)
    profiles = [profile for profile, _values in sampled]
    indexed = {(profile.collection_id, profile.column_name): profile for profile in profiles}
    context = ProfileContext(
        sample_values=config.sample_values,
        containment_threshold=config.containment_threshold,
    )
    drafts: list[LinkDraft] = []
    declared_pairs: set[tuple[str, str, str, str]] = set()
    for foreign_key in source.declared_links():
        if len(foreign_key.src_columns) != 1 or len(foreign_key.dst_columns) != 1:
            continue
        src = _column(
            indexed,
            foreign_key.src_collection,
            foreign_key.src_columns[0],
        )
        dst = _column(
            indexed,
            foreign_key.dst_collection,
            foreign_key.dst_columns[0],
        )
        candidate = matchers["declared_fk"].discover(src, dst, context)
        if candidate is None:
            continue
        drafts.append(
            _draft(
                src,
                dst,
                candidate,
                origin="catalog_fk",
                status="approved",
                cardinality="N:1",
                threshold=None,
            )
        )
        declared_pairs.add(_pair(src, dst))

    profiled = [ProfiledColumn(profile, values) for profile, values in sampled]
    for pair in candidate_pairs(profiled, config):
        key = _pair(pair.source, pair.destination)
        if key in declared_pairs:
            continue
        candidate = matchers["exact"].discover(pair.source, pair.destination, context)
        if candidate is None:
            continue
        drafts.append(
            _draft(
                pair.source,
                pair.destination,
                candidate,
                origin="discovered",
                status="proposed",
                cardinality=None,
                threshold=config.containment_threshold,
            )
        )
    return profiles, drafts


def _column(
    indexed: dict[tuple[str, str], ColumnProfile],
    collection_id: str,
    column_name: str,
) -> ColumnProfile:
    found = indexed.get((collection_id, column_name))
    if found is not None:
        return found
    return ColumnProfile(
        collection_id=collection_id,
        column_name=column_name,
        type_class="text",
    )


def _draft(
    src: ColumnProfile,
    dst: ColumnProfile,
    candidate: Candidate,
    *,
    origin: str,
    status: str,
    cardinality: str | None,
    threshold: float | None,
) -> LinkDraft:
    return LinkDraft(
        link_id=link_id(src.collection_id, src.column_name, dst.collection_id, dst.column_name),
        src_collection=src.collection_id,
        src_column=src.column_name,
        dst_collection=dst.collection_id,
        dst_column=dst.column_name,
        match_type=candidate.match_type,
        origin=origin,
        threshold=threshold,
        confidence=candidate.confidence,
        cardinality=cardinality,
        status=status,
        evidence=dict(candidate.evidence),
    )


def _pair(src: ColumnProfile, dst: ColumnProfile) -> tuple[str, str, str, str]:
    return (src.collection_id, src.column_name, dst.collection_id, dst.column_name)


def _collection_label(collection_id: str) -> str:
    if "://" in collection_id:
        collection_id = collection_id.split("://", 1)[1]
        collection_id = collection_id.split("/", 1)[-1]
    return collection_id

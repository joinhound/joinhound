# SPDX-License-Identifier: Apache-2.0

"""Values shared by connectors, the profiler, and the query engine."""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field


class Capabilities(BaseModel):
    """What a source can execute itself instead of through the local index."""

    pushdown_exact: bool
    pushdown_normalized: bool
    incremental: bool
    acl: bool


class CollectionInfo(BaseModel):
    """A table or document prefix discovered from a source."""

    collection_id: str
    name: str
    kind: Literal["table", "documents"]


class ColumnStats(BaseModel):
    """Statistics a connector can read without scanning the whole table."""

    column_name: str
    type_class: str
    n_distinct: float | None = None
    null_ratio: float | None = None


class DeclaredFK(BaseModel):
    """A foreign key declared by the source catalog."""

    src_collection: str
    src_columns: list[str]
    dst_collection: str
    dst_columns: list[str]


class Record(BaseModel):
    """One row or passage addressed by a provenance URI."""

    uri: str
    collection_id: str
    pk: dict[str, object]
    values: dict[str, object]


class Match(BaseModel):
    """A value found in a column, with the key of the row that holds it."""

    pk: dict[str, object]
    value: str
    score: float = 1.0


class TextBlock(BaseModel):
    """Text extracted from one region of a document."""

    text: str
    page: int
    bbox: tuple[float, float, float, float]


class IndexedPassage(BaseModel):
    """One stored fragment the query engine can rank and return."""

    uri: str
    collection_id: str
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    roles: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None


class DocRef(BaseModel):
    """A document that a document source can read."""

    uri: str
    etag: str | None = None
    deleted: bool = False


class AccessInfo(BaseModel):
    """Roles allowed to read a document or collection."""

    roles: list[str] = Field(default_factory=list)


class Cursor(BaseModel):
    """Opaque position for an incremental source scan."""

    value: str


class ColumnProfile(BaseModel):
    """Summary of one column used while discovering relationships."""

    collection_id: str
    column_name: str
    type_class: str
    n_distinct: float | None = None
    null_ratio: float | None = None
    uniqueness: float | None = None
    pattern: str | None = None
    minhash: bytes | None = None


class CollectionProfile(BaseModel):
    """Summary of one document collection used while discovering relationships."""

    collection_id: str


class ProfileContext(BaseModel):
    """Inputs available to a matcher while it looks for candidate relationships."""

    sample_values: int = 10000
    containment_threshold: float = 0.5


class QueryContext(BaseModel):
    """Inputs available to a matcher while it resolves one relationship."""

    limit: int = 50


EvidenceValue = str | int | float | bool | None | list[str]


class Candidate(BaseModel):
    """A proposed relationship that has not yet been stored."""

    match_type: str
    confidence: float
    evidence: dict[str, EvidenceValue] = Field(default_factory=dict)


class LinkDraft(BaseModel):
    """A relationship ready to be written to kg.links."""

    link_id: str
    src_collection: str
    src_column: str
    dst_collection: str
    dst_column: str | None = None
    match_type: str
    origin: str
    threshold: float | None = None
    confidence: float
    cardinality: str | None = None
    normalize_sql: str | None = None
    relation_name: str | None = None
    status: str
    evidence: dict[str, EvidenceValue] = Field(default_factory=dict)


class Link(BaseModel):
    """A stored relationship rule between columns or a column and documents."""

    link_id: str
    match_type: str
    src_collection: str
    src_column: str
    dst_collection: str
    dst_column: str | None = None
    normalize_sql: str | None = None


class JudgeVerdict(BaseModel):
    """Structured decision returned by a relationship judge."""

    is_meaningful: bool
    relation_name: str
    direction: str
    cardinality: str
    confidence: float
    rationale: str


def as_record(
    uri: str,
    collection_id: str,
    pk: Mapping[str, object],
    values: Mapping[str, object],
) -> Record:
    """Build a record without sharing the caller's mutable mappings."""
    return Record(uri=uri, collection_id=collection_id, pk=dict(pk), values=dict(values))

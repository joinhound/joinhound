# SPDX-License-Identifier: Apache-2.0

"""Response returned by one context query."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContextNode(BaseModel):
    """One row or passage selected for the answer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    uri: str
    kind: Literal["row", "passage"]
    collection: str
    content: dict[str, Any] | str
    score: float
    seed: bool


class ContextEdge(BaseModel):
    """A relationship between two nodes that were both returned."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(validation_alias="from", serialization_alias="from")
    to: str
    link_id: str
    relation: str
    match_type: str
    score: float


class ContextStats(BaseModel):
    """How much of the graph the query walked and returned."""

    model_config = ConfigDict(extra="forbid")

    seeds: int
    visited: int
    returned: int
    tokens: int
    ms: int


class RecordResult(BaseModel):
    """One full row or passage addressed by a source URI."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    collection: str
    kind: Literal["row", "passage"]
    content: dict[str, Any] | str
    neighbors: list[str]


class ContextResponse(BaseModel):
    """The graph returned by get_context and expand."""

    model_config = ConfigDict(extra="forbid")

    query: str
    nodes: list[ContextNode]
    edges: list[ContextEdge]
    paths: list[list[str]]
    truncated: bool
    expandable: list[str]
    stats: ContextStats

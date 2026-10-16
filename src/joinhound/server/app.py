# SPDX-License-Identifier: Apache-2.0

"""MCP tools for context, expansion, and single records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from mcp.server.mcpserver import MCPServer

from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.core.protocols import LinkMatcher, TabularSource
from joinhound.core.registry import load_plugins
from joinhound.engine.context import expand, get_context, read_record
from joinhound.engine.response import ContextResponse, RecordResult
from joinhound.engine.score import text_tokens, truncate_text
from joinhound.index.documents import read_passages
from joinhound.matchers.documents import Passage
from joinhound.server.runtime import Runtime

_SUMMARY_TOKENS = 2000

_GET_CONTEXT = (
    "Find records related to a question and return a bounded graph. Call this first. "
    "Each node carries a source uri. If truncated is true, call expand with the uri of "
    "each expandable node. expandable lists node ids, not uris. "
    "This server retrieves related records. It does not count, aggregate, or run SQL."
)
_EXPAND = (
    "Add neighbors of records already returned. Pass node uris from get_context or expand, "
    "not node ids. Call this when truncated is true. depth is the number of hops to follow, "
    "and links limits which relationship ids are used. "
    "This server retrieves related records. It does not count, aggregate, or run SQL."
)
_GET_RECORD = (
    "Read one record by its source uri and return the full row. Use a uri from get_context "
    "or expand. A passage uri will include neighboring fragments when documents are indexed. "
    "This server retrieves related records. It does not count, aggregate, or run SQL."
)
_SUMMARY = (
    "Collections and approved relationships, as Markdown. "
    "Read this to see which links exist before calling get_context."
)


def create_server(runtime: Runtime) -> MCPServer:
    """Build the stdio MCP server. The official SDK exposes this as MCPServer."""
    server: MCPServer = MCPServer("joinhound")

    @server.tool(name="get_context", description=_GET_CONTEXT)
    def get_context_tool(
        query: str,
        budget_tokens: int = 4000,
        scope: list[str] | None = None,
        max_depth: int = 3,
    ) -> ContextResponse:
        with runtime.session() as (sources, links):
            passages = _stored_passages(runtime)
            parts = [
                get_context(
                    query,
                    source,
                    _links_for(name, source, links),
                    _matchers(source, passages),
                    runtime.engine,
                    budget_tokens=budget_tokens,
                    max_depth=max_depth,
                    scope=scope,
                    passages=passages,
                )
                for name, source in sources
            ]
        return _merge(query, parts)

    @server.tool(name="expand", description=_EXPAND)
    def expand_tool(
        node_uris: list[str],
        depth: int = 1,
        budget_tokens: int = 2000,
        links: list[str] | None = None,
    ) -> ContextResponse:
        with runtime.session() as (sources, stored):
            passages = _stored_passages(runtime)
            parts = []
            for name, source in sources:
                owned = [uri for uri in node_uris if _owned(name, source, uri)]
                if not owned:
                    continue
                parts.append(
                    expand(
                        owned,
                        source,
                        _links_for(name, source, stored),
                        _matchers(source, passages),
                        runtime.engine,
                        depth=depth,
                        budget_tokens=budget_tokens,
                        link_ids=links,
                    )
                )
        return _merge(" ".join(node_uris), parts)

    @server.tool(name="get_record", description=_GET_RECORD)
    def get_record(uri: str) -> RecordResult:
        with runtime.session() as (sources, _links):
            for name, source in sources:
                if not _owned(name, source, uri):
                    continue
                return read_record(uri, source)
        raise ValueError(f"No source can read {uri}")

    @server.resource(
        "ontology://summary",
        name="summary",
        description=_SUMMARY,
        mime_type="text/markdown",
    )
    def ontology_summary() -> str:
        with runtime.session() as (sources, links):
            return _summary(sources, links)

    return server


def _stored_passages(runtime: Runtime) -> list[IndexedPassage]:
    if runtime.settings is None:
        return []
    return read_passages(runtime.settings.kg_database)


def _matchers(source: TabularSource, passages: Sequence[IndexedPassage]) -> dict[str, LinkMatcher]:
    plugins = load_plugins("joinhound.matchers")
    matchers: dict[str, LinkMatcher] = {}
    for name in ("declared_fk", "exact", "column_documents"):
        factory = plugins.get(name)
        if not callable(factory):
            continue
        if name == "column_documents":
            converted = [
                Passage(passage.collection_id, {"uri": passage.uri}, passage.text)
                for passage in passages
            ]
            matchers[name] = cast(LinkMatcher, factory(source, converted))
            continue
        matchers[name] = cast(LinkMatcher, factory(source))
    return matchers


def _links_for(name: str, source: TabularSource, links: list[LinkDraft]) -> list[LinkDraft]:
    known = {info.collection_id for info in source.list_collections()}
    prefix = f"pg://{name}/"
    return [
        link
        for link in links
        if link.src_collection in known
        or link.dst_collection in known
        or link.src_collection.startswith(prefix)
        or link.dst_collection.startswith(prefix)
    ]


def _owned(name: str, source: TabularSource, uri: str) -> bool:
    known = {info.collection_id for info in source.list_collections()}
    if any(uri.startswith(collection) for collection in known):
        return True
    return uri.startswith(f"pg://{name}/")


def _merge(query: str, parts: list[ContextResponse]) -> ContextResponse:
    if not parts:
        return ContextResponse(
            query=query,
            nodes=[],
            edges=[],
            paths=[],
            truncated=False,
            expandable=[],
            stats={"seeds": 0, "visited": 0, "returned": 0, "tokens": 0, "ms": 0},
        )
    if len(parts) == 1:
        return parts[0].model_copy(update={"query": query})
    nodes = []
    edges = []
    paths = []
    expandable = []
    id_map: dict[tuple[int, str], str] = {}
    next_id = 1
    for index, part in enumerate(parts):
        for node in part.nodes:
            new_id = f"n{next_id}"
            next_id += 1
            id_map[(index, node.id)] = new_id
            nodes.append(node.model_copy(update={"id": new_id}))
        for edge in part.edges:
            edges.append(
                edge.model_copy(
                    update={
                        "from_": id_map[(index, edge.from_)],
                        "to": id_map[(index, edge.to)],
                    }
                )
            )
        for path in part.paths:
            paths.append([id_map[(index, node_id)] for node_id in path])
        for node_id in part.expandable:
            expandable.append(id_map[(index, node_id)])
    return ContextResponse(
        query=query,
        nodes=nodes,
        edges=edges,
        paths=paths,
        truncated=any(part.truncated for part in parts),
        expandable=expandable,
        stats={
            "seeds": sum(part.stats.seeds for part in parts),
            "visited": sum(part.stats.visited for part in parts),
            "returned": len(nodes),
            "tokens": sum(part.stats.tokens for part in parts),
            "ms": max(part.stats.ms for part in parts),
        },
    )


def _summary(sources: list[tuple[str, TabularSource]], links: list[LinkDraft]) -> str:
    lines = ["# Ontology", "", "## Collections"]
    for _name, source in sources:
        for info in source.list_collections():
            lines.append(f"- `{info.collection_id}` ({info.kind})")
    lines.extend(["", "## Links"])
    for link in links:
        if link.status != "approved":
            continue
        relation = link.relation_name or link.link_id
        lines.append(f"- `{link.link_id}` ({link.match_type}): {relation}")
    text = "\n".join(lines) + "\n"
    if text_tokens(text) <= _SUMMARY_TOKENS:
        return text
    return truncate_text(text, _SUMMARY_TOKENS)

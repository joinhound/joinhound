# SPDX-License-Identifier: Apache-2.0

"""Find seed rows and walk approved links within a token budget."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from joinhound.core.config import EngineConfig
from joinhound.core.models import IndexedPassage, Link, LinkDraft, Match, QueryContext, Record
from joinhound.core.protocols import Embedder, LinkMatcher, TabularSource
from joinhound.core.uri import MssqlUri, PgUri, S3Uri, parse_uri
from joinhound.engine.cache import ResultCache, cache_key
from joinhound.engine.dictionary import ValueDictionary, build_dictionary
from joinhound.engine.lookup import Deployment, direct_records, normalized_matches
from joinhound.engine.passages import (
    lexical_rank,
    reciprocal_rank_fusion,
    semantic_rank,
    visible_passages,
)
from joinhound.engine.response import (
    ContextEdge,
    ContextNode,
    ContextResponse,
    ContextStats,
    RecordResult,
)
from joinhound.engine.score import content_tokens, path_score, relevance

_EXACT = frozenset({"declared_fk", "exact"})
_WALK = _EXACT | {"normalized", "fuzzy", "semantic"}
_DOCUMENTS = "column_documents"


@dataclass
class _Edge:
    link_id: str
    relation: str
    match_type: str
    score: float


@dataclass
class _Node:
    uri: str
    record: Record
    content: dict[str, Any]
    score: float
    seed: bool
    depth: int
    parent: _Node | None
    edge: _Edge | None
    edge_scores: tuple[float, ...]
    clipped: bool = False
    kind: Literal["row", "passage"] = "row"
    children: list[_Node] = field(default_factory=list)


def get_context(
    query: str,
    source: TabularSource,
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    settings: EngineConfig | None = None,
    *,
    budget_tokens: int | None = None,
    max_depth: int | None = None,
    scope: Sequence[str] | None = None,
    dictionary: ValueDictionary | None = None,
    clock: Callable[[], float] | None = None,
    passages: Sequence[IndexedPassage] = (),
    roles: Sequence[str] | None = None,
    embedder: Embedder | None = None,
    deployment: Deployment = "sidecar",
    cache: ResultCache | None = None,
) -> ContextResponse:
    """Return the highest-scoring rows and passages reachable from the query."""
    config = settings or EngineConfig()
    budget = config.budget_tokens if budget_tokens is None else budget_tokens
    depth_limit = config.max_depth if max_depth is None else max_depth
    now = (clock or time.monotonic)()
    key = cache_key(
        query,
        budget=budget,
        depth=depth_limit,
        scope=scope,
        deployment=deployment,
        links=links,
        roles=roles,
        passages=passages,
    )
    if cache is not None:
        cached = cache.get(key, now)
        if cached is not None:
            return cached
    tabular = [link for link in links if link.status == "approved" and link.dst_column is not None]
    documents = [
        link for link in links if link.status == "approved" and link.match_type == _DOCUMENTS
    ]
    dictionary_links = [*tabular, *documents]
    words = dictionary if dictionary is not None else build_dictionary(source, dictionary_links)
    readable = [
        passage
        for passage in visible_passages(passages, roles)
        if _in_scope(passage.collection_id, scope)
    ]
    seeds = _seed_nodes(
        query,
        source,
        words,
        config.seeds_k,
        scope,
        config.depth_decay,
        readable,
        embedder,
        deployment,
    )
    approved = [*tabular, *documents]
    result = _walk(
        query,
        source,
        approved,
        matchers,
        config,
        seeds,
        budget=budget,
        depth_limit=depth_limit,
        scope=scope,
        scoring_query=query,
        clock=clock,
        passages=readable,
        roles=roles,
        deployment=deployment,
    )
    if cache is not None:
        cache.put(key, result, now)
    return result


def expand(
    node_uris: Sequence[str],
    source: TabularSource,
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    settings: EngineConfig | None = None,
    *,
    depth: int = 1,
    budget_tokens: int = 2000,
    link_ids: Sequence[str] | None = None,
    clock: Callable[[], float] | None = None,
    deployment: Deployment = "sidecar",
) -> ContextResponse:
    """Walk outward from records the caller already identified."""
    config = settings or EngineConfig()
    approved = [link for link in links if link.status == "approved" and link.dst_column is not None]
    if link_ids is not None:
        wanted = set(link_ids)
        approved = [link for link in approved if link.link_id in wanted]
    seeds = _nodes_from_uris(source, node_uris)
    scoring_query = " ".join(_text(node.content) for node in seeds)
    return _walk(
        " ".join(node_uris),
        source,
        approved,
        matchers,
        config,
        seeds,
        budget=budget_tokens,
        depth_limit=depth,
        scope=None,
        scoring_query=scoring_query,
        clock=clock,
        deployment=deployment,
    )


def read_record(uri: str, source: TabularSource) -> RecordResult:
    """Return the full row for a provenance URI."""
    record = _fetch_record(source, uri, _known_collections(source))
    return RecordResult(
        uri=record.uri,
        collection=record.collection_id,
        kind="row",
        content=_content(record),
        neighbors=[],
    )


def _walk(
    query: str,
    source: TabularSource,
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    config: EngineConfig,
    seeds: list[_Node],
    *,
    budget: int,
    depth_limit: int,
    scope: Sequence[str] | None,
    scoring_query: str,
    clock: Callable[[], float] | None,
    passages: Sequence[IndexedPassage] = (),
    roles: Sequence[str] | None = None,
    deployment: Deployment = "sidecar",
) -> ContextResponse:
    now = clock or time.monotonic
    started = now()
    deadline = started + config.timeout_ms / 1000
    visited = {node.uri for node in seeds}
    discovered = list(seeds)
    beam = _frontier(seeds, config.beam_width)
    depth = 0
    timed_out = False
    while depth < depth_limit and beam and config.fanout > 0:
        if now() >= deadline:
            timed_out = True
            break
        expanded = _expand(
            beam,
            links,
            matchers,
            source,
            config.fanout,
            visited,
            scope,
            scoring_query,
            config.depth_decay,
            passages,
            roles,
            deployment,
        )
        discovered.extend(expanded)
        depth += 1
        beam = _frontier(expanded, config.beam_width)
    if timed_out or depth >= depth_limit:
        for node in beam:
            node.clipped = True
    chosen, used, truncated = _fit(discovered, budget)
    if timed_out:
        truncated = True
    nodes, edges, paths, expandable = _assemble(chosen)
    return ContextResponse(
        query=query,
        nodes=nodes,
        edges=edges,
        paths=paths,
        truncated=truncated,
        expandable=expandable,
        stats=ContextStats(
            seeds=len(seeds),
            visited=len(discovered),
            returned=len(nodes),
            tokens=used,
            ms=int((now() - started) * 1000),
        ),
    )


def _seed_nodes(
    query: str,
    source: TabularSource,
    dictionary: ValueDictionary,
    seeds_k: int,
    scope: Sequence[str] | None,
    decay: float,
    passages: Sequence[IndexedPassage],
    embedder: Embedder | None,
    deployment: Deployment,
) -> list[_Node]:
    if seeds_k <= 0:
        return []
    records = _ranked_records(query, source, dictionary, scope, deployment)
    by_uri = {record.uri: record for record in records}
    passage_by_uri = {passage.uri: passage for passage in passages}
    semantic: list[str] = []
    if embedder is not None and passages:
        vector = embedder.embed([query])
        if vector:
            semantic = semantic_rank(vector[0], passages)
    fused = reciprocal_rank_fusion(
        [
            [record.uri for record in records],
            lexical_rank(query, passages),
            semantic,
        ]
    )
    nodes: list[_Node] = []
    for uri in fused:
        if uri in by_uri:
            nodes.append(
                _make_node(by_uri[uri], query, (), decay, seed=True, parent=None, edge=None)
            )
        elif uri in passage_by_uri:
            nodes.append(
                _make_passage(
                    passage_by_uri[uri],
                    query,
                    (),
                    decay,
                    seed=True,
                    parent=None,
                    edge=None,
                )
            )
        if len(nodes) >= seeds_k:
            break
    return nodes


def _ranked_records(
    query: str,
    source: TabularSource,
    dictionary: ValueDictionary,
    scope: Sequence[str] | None,
    deployment: Deployment,
) -> list[Record]:
    grouped: dict[tuple[str, str], list[str]] = {}
    rank: dict[tuple[str, str, str], tuple[int, int]] = {}
    for mention in dictionary.mentions(query):
        if not _in_scope(mention.collection_id, scope):
            continue
        key = (mention.collection_id, mention.column)
        values = grouped.setdefault(key, [])
        if mention.value not in values:
            values.append(mention.value)
        rank.setdefault(key + (mention.value,), (len(mention.value), mention.start))
    ranked: list[tuple[tuple[int, int, str], Record]] = []
    for (collection_id, column), values in grouped.items():
        limit = max(len(values), 1) * 50
        loaded = direct_records(
            source, deployment, collection_id, column, values, "exact", None, limit
        )
        if loaded is None:
            matches = source.find_values(collection_id, column, values, "exact", limit=limit)
            records = {
                _pk_key(record.pk): record
                for record in source.fetch_by_keys(
                    collection_id, [dict(match.pk) for match in matches]
                )
            }
        else:
            matches = [
                Match(
                    pk=dict(record.pk),
                    value="" if record.values.get(column) is None else str(record.values[column]),
                    score=1.0,
                )
                for record in loaded
            ]
            records = {_pk_key(record.pk): record for record in loaded}
        for match in matches:
            record = records.get(_pk_key(match.pk))
            place = rank.get((collection_id, column, match.value))
            if record is None or place is None:
                continue
            length, start = place
            ranked.append(((-length, start, record.uri), record))
    ranked.sort(key=lambda item: item[0])
    chosen: list[Record] = []
    seen: set[str] = set()
    for _key, record in ranked:
        if record.uri in seen:
            continue
        seen.add(record.uri)
        chosen.append(record)
    return chosen


def _expand(
    beam: Sequence[_Node],
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    source: TabularSource,
    fanout: int,
    visited: set[str],
    scope: Sequence[str] | None,
    query: str,
    decay: float,
    passages: Sequence[IndexedPassage],
    roles: Sequence[str] | None,
    deployment: Deployment,
) -> list[_Node]:
    ordered = sorted(beam, key=lambda node: node.uri)
    found: list[_Node] = []
    for link in links:
        if link.match_type == _DOCUMENTS:
            found.extend(
                _follow_documents(
                    ordered,
                    link,
                    matchers,
                    source,
                    fanout,
                    visited,
                    scope,
                    query,
                    decay,
                    passages,
                    roles,
                )
            )
            continue
        if link.match_type not in _WALK or link.dst_column is None:
            continue
        found.extend(
            _follow(
                ordered,
                link,
                matchers,
                source,
                fanout,
                visited,
                scope,
                query,
                decay,
                deployment,
                forward=True,
            )
        )
        if link.match_type in _EXACT:
            found.extend(
                _follow(
                    ordered,
                    link,
                    matchers,
                    source,
                    fanout,
                    visited,
                    scope,
                    query,
                    decay,
                    deployment,
                    forward=False,
                )
            )
    return found


def _follow(
    nodes: Sequence[_Node],
    link: LinkDraft,
    matchers: Mapping[str, LinkMatcher],
    source: TabularSource,
    fanout: int,
    visited: set[str],
    scope: Sequence[str] | None,
    query: str,
    decay: float,
    deployment: Deployment,
    *,
    forward: bool,
) -> list[_Node]:
    if link.dst_column is None:
        return []
    origin = link.src_collection if forward else link.dst_collection
    destination = link.dst_collection if forward else link.src_collection
    column = link.src_column if forward else link.dst_column
    if not _in_scope(destination, scope):
        return []
    grouped: dict[str, list[_Node]] = {}
    for node in nodes:
        if node.record.collection_id != origin:
            continue
        raw = node.record.values.get(column)
        if raw is None:
            continue
        grouped.setdefault(str(raw), []).append(node)
    if not grouped:
        return []
    limit = fanout * len(grouped)
    search_column = link.dst_column if forward else link.src_column
    prefetched: dict[str, Record] | None = None
    matches: list[Match] | None = None
    if search_column is not None and link.match_type == "normalized" and forward:
        found = normalized_matches(
            source,
            deployment,
            destination,
            search_column,
            list(grouped),
            link.normalize_sql,
            limit,
        )
        if found is not None:
            matches, rows = found
            prefetched = {_pk_key(row.pk): row for row in rows}
    elif search_column is not None and link.match_type in _EXACT:
        loaded = direct_records(
            source,
            deployment,
            destination,
            search_column,
            list(grouped),
            "exact",
            None,
            limit,
        )
        if loaded is not None:
            prefetched = {_pk_key(row.pk): row for row in loaded}
            matches = [_exact_match(row, search_column) for row in loaded]
    if matches is None:
        if forward:
            matcher = matchers.get(link.match_type)
            if matcher is None:
                return []
            matches = matcher.resolve(_as_link(link), list(grouped), QueryContext(limit=limit))
        else:
            matches = [
                Match(pk=dict(match.pk), value=match.value, score=1.0)
                for match in source.find_values(
                    destination,
                    link.src_column,
                    list(grouped),
                    "exact",
                    limit=limit,
                )
            ]
    by_value: dict[str, list[Match]] = {}
    for match in matches:
        by_value.setdefault(match.value, []).append(match)
    created: list[_Node] = []
    for value, parents in grouped.items():
        ranked = sorted(by_value.get(value, []), key=lambda match: _pk_key(match.pk))
        if len(ranked) > fanout:
            for parent in parents:
                parent.clipped = True
        chosen = ranked[:fanout]
        if prefetched is None:
            records = {
                _pk_key(record.pk): record
                for record in source.fetch_by_keys(
                    destination, [dict(match.pk) for match in chosen]
                )
            }
        else:
            records = prefetched
        for match in chosen:
            record = records.get(_pk_key(match.pk))
            if record is None or record.uri in visited:
                continue
            if not _in_scope(record.collection_id, scope):
                continue
            visited.add(record.uri)
            edge_score = match.score * link.confidence
            parent = parents[0]
            edge = _Edge(link.link_id, link.relation_name or "", link.match_type, edge_score)
            child = _make_node(
                record,
                query,
                parent.edge_scores + (edge_score,),
                decay,
                seed=False,
                parent=parent,
                edge=edge,
            )
            parent.children.append(child)
            created.append(child)
    return created


def _follow_documents(
    nodes: Sequence[_Node],
    link: LinkDraft,
    matchers: Mapping[str, LinkMatcher],
    source: TabularSource,
    fanout: int,
    visited: set[str],
    scope: Sequence[str] | None,
    query: str,
    decay: float,
    passages: Sequence[IndexedPassage],
    roles: Sequence[str] | None,
) -> list[_Node]:
    matcher = matchers.get(link.match_type)
    if matcher is None or fanout <= 0:
        return []
    return [
        *_documents_from_rows(
            nodes, link, matcher, fanout, visited, scope, query, decay, passages, roles
        ),
        *_rows_from_passages(nodes, link, matcher, source, fanout, visited, scope, query, decay),
    ]


def _documents_from_rows(
    nodes: Sequence[_Node],
    link: LinkDraft,
    matcher: LinkMatcher,
    fanout: int,
    visited: set[str],
    scope: Sequence[str] | None,
    query: str,
    decay: float,
    passages: Sequence[IndexedPassage],
    roles: Sequence[str] | None,
) -> list[_Node]:
    if not _in_scope(link.dst_collection, scope):
        return []
    grouped: dict[str, list[_Node]] = {}
    for node in nodes:
        if node.kind != "row" or node.record.collection_id != link.src_collection:
            continue
        raw = node.record.values.get(link.src_column)
        if raw is None:
            continue
        grouped.setdefault(str(raw), []).append(node)
    if not grouped:
        return []
    matches = matcher.resolve(
        _as_link(link),
        list(grouped),
        QueryContext(limit=fanout * len(grouped)),
    )
    by_value: dict[str, list[Match]] = {}
    for match in matches:
        by_value.setdefault(match.value, []).append(match)
    allowed = {passage.uri: passage for passage in visible_passages(passages, roles)}
    created: list[_Node] = []
    for value, parents in grouped.items():
        chosen = by_value.get(value, [])[:fanout]
        for match in chosen:
            uri = match.pk.get("uri")
            passage = allowed.get(uri) if isinstance(uri, str) else None
            if passage is None or passage.uri in visited:
                continue
            if not _in_scope(passage.collection_id, scope):
                continue
            visited.add(passage.uri)
            parent = parents[0]
            edge_score = match.score * link.confidence
            edge = _Edge(link.link_id, link.relation_name or "", link.match_type, edge_score)
            child = _make_passage(
                passage,
                query,
                parent.edge_scores + (edge_score,),
                decay,
                seed=False,
                parent=parent,
                edge=edge,
            )
            parent.children.append(child)
            created.append(child)
    return created


def _rows_from_passages(
    nodes: Sequence[_Node],
    link: LinkDraft,
    matcher: LinkMatcher,
    source: TabularSource,
    fanout: int,
    visited: set[str],
    scope: Sequence[str] | None,
    query: str,
    decay: float,
) -> list[_Node]:
    mentions = getattr(matcher, "mentions", None)
    if not callable(mentions) or not _in_scope(link.src_collection, scope):
        return []
    created: list[_Node] = []
    for node in nodes:
        if node.kind != "passage" or node.record.collection_id != link.dst_collection:
            continue
        text = node.record.values.get("text")
        if not isinstance(text, str) or not text:
            continue
        matches = cast(
            list[Match],
            mentions(_as_link(link), text, QueryContext(limit=fanout)),
        )
        records = {
            _pk_key(record.pk): record
            for record in source.fetch_by_keys(
                link.src_collection,
                [dict(match.pk) for match in matches],
            )
        }
        for match in matches[:fanout]:
            record = records.get(_pk_key(match.pk))
            if record is None or record.uri in visited:
                continue
            if not _in_scope(record.collection_id, scope):
                continue
            visited.add(record.uri)
            edge_score = match.score * link.confidence
            edge = _Edge(link.link_id, link.relation_name or "", link.match_type, edge_score)
            child = _make_node(
                record,
                query,
                node.edge_scores + (edge_score,),
                decay,
                seed=False,
                parent=node,
                edge=edge,
            )
            node.children.append(child)
            created.append(child)
    return created


def _make_passage(
    passage: IndexedPassage,
    query: str,
    edge_scores: tuple[float, ...],
    decay: float,
    *,
    seed: bool,
    parent: _Node | None,
    edge: _Edge | None,
) -> _Node:
    record = Record(
        uri=passage.uri,
        collection_id=passage.collection_id,
        pk={"uri": passage.uri},
        values={"text": passage.text, "page": passage.page, "bbox": list(passage.bbox)},
    )
    node = _make_node(record, query, edge_scores, decay, seed=seed, parent=parent, edge=edge)
    node.kind = "passage"
    return node


def _make_node(
    record: Record,
    query: str,
    edge_scores: tuple[float, ...],
    decay: float,
    *,
    seed: bool,
    parent: _Node | None,
    edge: _Edge | None,
) -> _Node:
    content = _content(record)
    return _Node(
        uri=record.uri,
        record=record,
        content=content,
        score=path_score(relevance(query, _text(content)), edge_scores, decay),
        seed=seed,
        depth=0 if parent is None else parent.depth + 1,
        parent=parent,
        edge=edge,
        edge_scores=edge_scores,
    )


def _frontier(nodes: Sequence[_Node], width: int) -> list[_Node]:
    ordered = sorted(nodes, key=lambda node: (-node.score, node.uri))
    chosen = ordered[: max(width, 0)]
    kept = {node.uri for node in chosen}
    for node in nodes:
        if node.uri not in kept:
            node.clipped = True
    return chosen


def _fit(nodes: Sequence[_Node], budget: int) -> tuple[list[_Node], int, bool]:
    ordered = sorted(nodes, key=lambda node: (-node.score, node.uri))
    chosen: list[_Node] = []
    used = 0
    for node in ordered:
        cost = content_tokens(node.content)
        if used + cost > budget:
            return chosen, used, True
        chosen.append(node)
        used += cost
    return chosen, used, False


def _assemble(
    chosen: Sequence[_Node],
) -> tuple[list[ContextNode], list[ContextEdge], list[list[str]], list[str]]:
    ordered = sorted(chosen, key=lambda node: (-node.score, node.uri))
    id_by_uri = {node.uri: f"n{index + 1}" for index, node in enumerate(ordered)}
    nodes = [
        ContextNode(
            id=id_by_uri[node.uri],
            uri=node.uri,
            kind=node.kind,
            collection=node.record.collection_id,
            content=node.content,
            score=node.score,
            seed=node.seed,
        )
        for node in ordered
    ]
    edges: list[ContextEdge] = []
    paths: list[list[str]] = []
    expandable: list[str] = []
    for node in ordered:
        node_id = id_by_uri[node.uri]
        omitted = any(child.uri not in id_by_uri for child in node.children)
        if node.clipped or omitted:
            expandable.append(node_id)
        if node.parent is None or node.edge is None or node.parent.uri not in id_by_uri:
            continue
        edges.append(
            ContextEdge(
                from_=id_by_uri[node.parent.uri],
                to=node_id,
                link_id=node.edge.link_id,
                relation=node.edge.relation,
                match_type=node.edge.match_type,
                score=node.edge.score,
            )
        )
        path = _path(node, id_by_uri)
        if path is not None:
            paths.append(path)
    edges.sort(key=lambda edge: (edge.from_, edge.to, edge.link_id))
    paths.sort()
    return nodes, edges, paths, expandable


def _path(node: _Node, id_by_uri: Mapping[str, str]) -> list[str] | None:
    chain: list[str] = []
    current: _Node | None = node
    while current is not None:
        node_id = id_by_uri.get(current.uri)
        if node_id is None:
            return None
        chain.append(node_id)
        current = current.parent
    if len(chain) < 2:
        return None
    chain.reverse()
    return chain


def _content(record: Record) -> dict[str, Any]:
    content: dict[str, Any] = {}
    for key in sorted(record.values):
        value = record.values[key]
        if value is None:
            continue
        content[key] = _json_value(value)
    return content


def _json_value(value: object) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _text(content: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(content):
        value = content[key]
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            parts.append(str(value))
    return " ".join(parts)


def _as_link(draft: LinkDraft) -> Link:
    return Link(
        link_id=draft.link_id,
        match_type=draft.match_type,
        src_collection=draft.src_collection,
        src_column=draft.src_column,
        dst_collection=draft.dst_collection,
        dst_column=draft.dst_column,
        normalize_sql=draft.normalize_sql,
    )


def _in_scope(collection_id: str, scope: Sequence[str] | None) -> bool:
    if not scope:
        return True
    return any(collection_id.startswith(prefix) for prefix in scope)


def _exact_match(record: Record, column: str) -> Match:
    raw = record.values.get(column)
    return Match(pk=dict(record.pk), value="" if raw is None else str(raw), score=1.0)


def _pk_key(pk: Mapping[str, object]) -> str:
    return json.dumps(dict(pk), sort_keys=True, separators=(",", ":"), default=str)


def _nodes_from_uris(source: TabularSource, uris: Sequence[str]) -> list[_Node]:
    known = _known_collections(source)
    nodes: list[_Node] = []
    seen: set[str] = set()
    for uri in uris:
        if uri in seen:
            continue
        seen.add(uri)
        record = _fetch_record(source, uri, known)
        nodes.append(
            _Node(
                uri=record.uri,
                record=record,
                content=_content(record),
                score=1.0,
                seed=True,
                depth=0,
                parent=None,
                edge=None,
                edge_scores=(),
            )
        )
    return nodes


def _fetch_record(source: TabularSource, uri: str, known: set[str]) -> Record:
    parsed = parse_uri(uri)
    if isinstance(parsed, S3Uri):
        raise ValueError(f"Document passages are not available yet: {uri}")
    if not isinstance(parsed, PgUri | MssqlUri):
        raise ValueError(f"Unsupported record URI: {uri}")
    collection = _collection_id(parsed, known)
    found = source.fetch_by_keys(collection, [dict(parsed.pk)])
    wanted = _pk_key(parsed.pk)
    for record in found:
        if _pk_key(record.pk) == wanted:
            return record
    raise ValueError(f"No record at {uri}")


def _known_collections(source: TabularSource) -> set[str]:
    return {info.collection_id for info in source.list_collections()}


def _collection_id(uri: PgUri | MssqlUri, known: set[str]) -> str:
    scheme = "mssql" if isinstance(uri, MssqlUri) else "pg"
    qualified = f"{scheme}://{uri.source}/{uri.schema}.{uri.table}"
    if qualified in known:
        return qualified
    if uri.table in known:
        return uri.table
    return qualified

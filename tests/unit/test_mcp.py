# SPDX-License-Identifier: Apache-2.0

"""MCP tools return the context graph and keep their published schemas."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from joinhound.core.config import EngineConfig
from joinhound.core.models import DeclaredFK, LinkDraft
from joinhound.engine.response import ContextResponse
from joinhound.profiler.profile import link_id
from joinhound.server import Runtime, create_server
from joinhound.testing.memory import MemoryTabularSource

_LINK = link_id("cast", "film_id", "films", "id")


def test_tool_schemas_name_the_graph_and_the_limits() -> None:
    server = create_server(Runtime(engine=EngineConfig(), sources=[], links=[]))
    listed = asyncio.run(_listed(server))
    by_name = {tool.name: tool for tool in listed.tools}

    assert set(by_name) == {"get_context", "expand", "get_record"}
    assert "truncated" in (by_name["get_context"].description or "")
    assert "expandable" in (by_name["get_context"].description or "")
    assert "aggregat" in (by_name["get_context"].description or "")
    assert "aggregat" in (by_name["expand"].description or "")
    assert "aggregat" in (by_name["get_record"].description or "")
    assert set(by_name["get_context"].input_schema["properties"]) >= {
        "query",
        "budget_tokens",
        "scope",
        "max_depth",
    }
    assert set(by_name["expand"].input_schema["properties"]) >= {
        "node_uris",
        "depth",
        "budget_tokens",
        "links",
    }
    assert "uri" in by_name["get_record"].input_schema["properties"]
    for name in ("get_context", "expand"):
        schema = by_name[name].output_schema
        assert schema is not None
        rendered = json.dumps(schema)
        for field in ("query", "nodes", "edges", "paths", "truncated", "expandable", "stats"):
            assert field in rendered
        assert '"from"' in rendered
    record_schema = by_name["get_record"].output_schema
    assert record_schema is not None
    rendered_record = json.dumps(record_schema)
    for field in ("uri", "content", "neighbors"):
        assert field in rendered_record


def test_client_reads_a_graph_and_one_record() -> None:
    server = create_server(
        Runtime(
            engine=EngineConfig(fanout=10, budget_tokens=100_000),
            sources=[("memory", _source())],
            links=_links(),
        )
    )
    graph, expanded, record, summary = asyncio.run(_calls(server))

    film = next(node for node in graph.nodes if node.content.get("title") == "ACADEMY DINOSAUR")
    assert film.seed
    assert any(node.collection == "cast" for node in expanded.nodes)
    assert record["content"]["title"] == "ACADEMY DINOSAUR"
    assert record["neighbors"] == []
    assert "films" in summary
    assert _LINK in summary


def test_stdio_server_lists_tools_without_opening_a_database(tmp_path: Path) -> None:
    listed = asyncio.run(_stdio_tools(tmp_path / "joinhound.yaml"))
    assert {tool.name for tool in listed.tools} == {"get_context", "expand", "get_record"}


async def _listed(server: object) -> object:
    from mcp.server.mcpserver import MCPServer

    assert isinstance(server, MCPServer)
    async with Client(server) as client:
        return await client.list_tools()


async def _calls(server: object) -> tuple[ContextResponse, ContextResponse, dict[str, object], str]:
    from mcp.server.mcpserver import MCPServer

    assert isinstance(server, MCPServer)
    async with Client(server) as client:
        resources = await client.list_resources()
        assert [str(resource.uri) for resource in resources.resources] == ["ontology://summary"]
        found = await client.call_tool("get_context", {"query": "ACADEMY DINOSAUR", "max_depth": 1})
        assert found.structured_content is not None
        graph = ContextResponse.model_validate(found.structured_content)
        film = next(node for node in graph.nodes if node.content.get("title") == "ACADEMY DINOSAUR")
        expanded_result = await client.call_tool(
            "expand",
            {"node_uris": [film.uri], "depth": 1, "budget_tokens": 100000},
        )
        assert expanded_result.structured_content is not None
        expanded = ContextResponse.model_validate(expanded_result.structured_content)
        record_result = await client.call_tool("get_record", {"uri": film.uri})
        assert record_result.structured_content is not None
        summary = await client.read_resource("ontology://summary")
        text = summary.contents[0].text if hasattr(summary.contents[0], "text") else ""
        return graph, expanded, record_result.structured_content, text


async def _stdio_tools(config: Path) -> object:
    config.write_text(
        "\n".join(
            [
                "mode: sidecar",
                "kg_database: postgresql://joinhound:joinhound@127.0.0.1:1/joinhound",
                "sources: {}",
                "embeddings:",
                "  provider: none",
                "  model: none",
                "  dim: 1024",
                "judge:",
                "  provider: none",
                "",
            ]
        ),
        encoding="utf-8",
    )
    command = Path(sys.executable).with_name("joinhound")
    try:
        async with Client(
            StdioServerParameters(command=str(command), args=["serve", "--config", str(config)])
        ) as client:
            return await client.list_tools()
    finally:
        config.unlink(missing_ok=True)


def _source() -> MemoryTabularSource:
    return MemoryTabularSource(
        {
            "films": [{"id": 1, "title": "ACADEMY DINOSAUR"}],
            "cast": [{"id": 100, "film_id": 1, "actor_id": 10, "note": "one"}],
        },
        [
            DeclaredFK(
                src_collection="cast",
                src_columns=["film_id"],
                dst_collection="films",
                dst_columns=["id"],
            )
        ],
    )


def _links() -> list[LinkDraft]:
    return [
        LinkDraft(
            link_id=_LINK,
            src_collection="cast",
            src_column="film_id",
            dst_collection="films",
            dst_column="id",
            match_type="declared_fk",
            origin="catalog_fk",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        )
    ]

# SPDX-License-Identifier: Apache-2.0

"""Profile, sync, get_context, and model calls emit OpenTelemetry spans."""

import asyncio
import json

from mcp import Client
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from typer.testing import CliRunner

from joinhound.cli import app
from joinhound.core.config import EngineConfig
from joinhound.core.models import Candidate
from joinhound.llm.openai_embedder import OpenAIEmbedder
from joinhound.llm.openai_judge import OpenAIJudge
from joinhound.server import Runtime, create_server
from joinhound.telemetry import span

_CONFIG = """
mode: sidecar
kg_database: postgresql://joinhound@localhost/joinhound
sources: {}
embeddings:
  provider: none
  model: none
  dim: 1024
judge:
  provider: none
"""


def test_profile_sync_and_get_context_emit_spans(monkeypatch, tmp_path) -> None:
    exporter = _capture(monkeypatch)
    config = tmp_path / "joinhound.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    runner = CliRunner()

    profiled = runner.invoke(app, ["profile", "--config", str(config)])
    synced = runner.invoke(app, ["sync", "--config", str(config)])
    asyncio.run(_context())

    assert profiled.exit_code == 0, profiled.output
    assert synced.exit_code == 0, synced.output
    names = {item.name for item in exporter.get_finished_spans()}
    assert {"joinhound.profile", "joinhound.sync", "joinhound.get_context"} <= names


def test_model_calls_use_genai_attribute_names(monkeypatch) -> None:
    exporter = _capture(monkeypatch)
    OpenAIJudge(model="judge-model", client=_Chat()).review(
        Candidate(match_type="exact", confidence=0.6, evidence={})
    )
    OpenAIEmbedder(dim=3, model="embed-model", client=_Embeddings()).embed(["alpha"])

    by_name = {
        item.name: dict(item.attributes or {}) for item in exporter.get_finished_spans()
    }
    assert by_name["gen_ai.chat"]["gen_ai.operation.name"] == "chat"
    assert by_name["gen_ai.chat"]["gen_ai.request.model"] == "judge-model"
    assert by_name["gen_ai.embeddings"]["gen_ai.operation.name"] == "embeddings"
    assert by_name["gen_ai.embeddings"]["gen_ai.request.model"] == "embed-model"
    assert "alpha" not in json.dumps(by_name)


def _capture(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "joinhound.telemetry.trace.get_tracer",
        lambda name, *args, **kwargs: provider.get_tracer(name),
    )
    return exporter


async def _context() -> None:
    server = create_server(Runtime(engine=EngineConfig(), sources=[], links=[]))
    async with Client(server) as client:
        await client.call_tool("get_context", {"query": "nothing"})


class _Message:
    content = (
        '{"is_meaningful": true, "relation_name": "has", "direction": "forward", '
        '"cardinality": "N:1", "confidence": 0.8, "rationale": "ok"}'
    )


class _Choice:
    message = _Message()


class _ChatResponse:
    choices = [_Choice()]


class _Completions:
    def create(self, **kwargs: object) -> _ChatResponse:
        return _ChatResponse()


class _ChatApi:
    completions = _Completions()


class _Chat:
    chat = _ChatApi()


class _Item:
    embedding = [0.1, 0.2, 0.3]


class _EmbedResponse:
    data = [_Item()]


class _EmbedApi:
    def create(self, **kwargs: object) -> _EmbedResponse:
        return _EmbedResponse()


class _Embeddings:
    embeddings = _EmbedApi()


def test_span_helper_sets_attributes(monkeypatch) -> None:
    exporter = _capture(monkeypatch)
    with span("joinhound.profile", {"gen_ai.system": "openai"}):
        pass
    finished = exporter.get_finished_spans()
    assert finished[-1].attributes is not None
    assert finished[-1].attributes["gen_ai.system"] == "openai"

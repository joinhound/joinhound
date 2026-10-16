# SPDX-License-Identifier: Apache-2.0

"""One exported span is visible in Jaeger."""

import json
import time
import urllib.request

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs


def test_a_get_context_span_is_visible_in_jaeger() -> None:
    with (
        DockerContainer("jaegertracing/all-in-one:1.62.0")
        .with_exposed_ports(16686, 4318)
        .with_env("COLLECTOR_OTLP_ENABLED", "true")
    ) as jaeger:
        wait_for_logs(jaeger, "Query server started", timeout=60)
        host = jaeger.get_container_host_ip()
        otlp_port = jaeger.get_exposed_port(4318)
        query_port = jaeger.get_exposed_port(16686)
        _export(host, otlp_port)
        found = _wait_for_trace(host, query_port)

    assert found


def _export(host: str, port: str) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": "joinhound"}))
    exporter = OTLPSpanExporter(endpoint=f"http://{host}:{port}/v1/traces")
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("joinhound").start_as_current_span("joinhound.get_context"):
        pass
    provider.force_flush()


def _wait_for_trace(host: str, port: str) -> bool:
    url = f"http://{host}:{port}/api/traces?service=joinhound&limit=20"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode())
        except OSError:
            time.sleep(0.5)
            continue
        data = payload.get("data", [])
        if any(_has_context(trace) for trace in data):
            return True
        time.sleep(0.5)
    return False


def _has_context(trace: object) -> bool:
    if not isinstance(trace, dict):
        return False
    spans = trace.get("spans", [])
    return any(
        isinstance(item, dict) and item.get("operationName") == "joinhound.get_context"
        for item in spans
    )

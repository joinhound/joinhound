# SPDX-License-Identifier: Apache-2.0

"""OpenTelemetry spans for profile, sync, get_context, and model calls."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False


def configure() -> None:
    """Export spans when an OTLP endpoint is configured. Otherwise keep the no-op tracer."""
    global _configured
    if _configured:
        return
    traces = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not traces and not base:
        return
    endpoint = traces or f"{base.rstrip('/')}/v1/traces"
    provider = TracerProvider(resource=Resource.create({"service.name": "joinhound"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _configured = True


@contextmanager
def span(name: str, attributes: Mapping[str, str] | None = None) -> Iterator[None]:
    """Open one span. Attribute values are names, never customer data."""
    current = trace.get_tracer("joinhound").start_as_current_span(name)
    with current as active:
        for key, value in (attributes or {}).items():
            active.set_attribute(key, value)
        yield

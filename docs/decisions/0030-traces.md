# Traces

Profile, sync, and `get_context` each open one span: `joinhound.profile`, `joinhound.sync`, and `joinhound.get_context`. A judge call opens `gen_ai.chat` and an embedding call opens `gen_ai.embeddings`, with `gen_ai.operation.name`, `gen_ai.request.model`, and `gen_ai.system`.

Spans carry those names only. They do not carry the query, the prompt, column values, or the bearer token.

When `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set, the process exports OTLP over HTTP. `docker compose` includes Jaeger on ports 16686 (UI) and 4318 (OTLP). With the endpoint unset, the tracer does nothing.

`protobuf` declares its license as "3-Clause BSD License". That is the BSD-3-Clause license already allowed by the project, so the checker accepts that declaration string.

## Alternatives

- Log the prompt on the span so a trace explains a verdict. The prompt can contain customer values, and the logs are not supposed to.
- Always start an exporter. A local stdio process would then try to reach a collector that is not there.

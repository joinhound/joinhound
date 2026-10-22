# Changelog

## 0.1.0

First release for a pilot.

- Read-only PostgreSQL and S3 connectors. The service database holds metadata and indexes. Customer sources are not written.
- Column profiling, Ossie import and export, and sync of approved fuzzy and semantic values and of changed documents.
- Exact, normalized, fuzzy, and semantic matchers, including links from a column to a document collection.
- MCP tools `get_context`, `expand`, and `get_record` over stdio, and over Streamable HTTP with a bearer token.
- Sidecar and co-located executors. A `get_context` response is cached only until its TTL.
- OpenTelemetry spans for profiling, sync, `get_context`, and model calls.

Pushing a `v0.1.0` tag publishes the package to PyPI and the image to `ghcr.io/joinhound/joinhound`.

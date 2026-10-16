# 0014. MCP stdio server

## Context

T1.7 requires `get_context`, `expand`, `get_record`, the `ontology://summary` resource, output schemas, and descriptions a model can follow. The specification names FastMCP. The current official package is `mcp` 2.3.0, which exposes `MCPServer` instead. HTTP transport and document passages are specified, but this task is the stdio server and the document index does not exist yet. `cffi`, pulled in by the SDK, declares MIT-0.

## Decision

The server is `MCPServer` from `mcp` 2.3.0. `joinhound serve` uses stdio. A configured `http` transport is rejected until that transport is implemented.

`expand` walks from the given row URIs with the same beam, fanout, and token budget as `get_context`. `get_record` returns the full row and an empty neighbor list. An S3 URI fails with an error that document passages are not available yet. The ontology resource is Markdown of collections and approved links, cut at 2,000 cl100k tokens.

MIT-0 is accepted. It is MIT without the attribution clause.

## Alternatives

- Pin an older `mcp` release that still names FastMCP. The current SDK is the one clients negotiate with.
- Implement Streamable HTTP in this task. The done criterion is a stdio connection.
- Invent neighboring passages for rows. The specification attaches those to document fragments.

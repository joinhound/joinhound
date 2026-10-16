# HTTP bearer token

The Streamable HTTP transport compares the `Authorization: Bearer` value with `server.auth_token`. A request without that header, or with a different token, is rejected with HTTP 401. stdio stays open for a local process.

The MCP Python SDK can also run a full OAuth 2.1 authorization server. This release does not. The configured string is a shared secret, checked with `secrets.compare_digest`, and the SDK `TokenVerifier` slot is where a later issuer can be plugged in. `AuthSettings.issuer_url` and `resource_server_url` are the local listen URL so the protected-resource metadata has a valid address.

## Alternatives

- Ship dynamic client registration and an authorization-code flow now. The stage exit test only requires that a missing token is rejected, and a local shared secret is what the configuration already has.
- Leave HTTP unimplemented until an external identity provider is chosen. The container transport would stay blocked on that choice.

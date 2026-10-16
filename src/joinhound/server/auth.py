# SPDX-License-Identifier: Apache-2.0

"""Static bearer token for the HTTP transport."""

from __future__ import annotations

import secrets

from mcp.server.auth.provider import AccessToken


class StaticTokenVerifier:
    """Accept one configured bearer token. A missing or different token is refused."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("HTTP transport requires a bearer token")
        self._token = token

    def authenticate(self, token: str) -> bool:
        """Return whether this token is the configured one."""
        return secrets.compare_digest(token, self._token)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return MCP access info, or nothing when the bearer does not match."""
        if not self.authenticate(token):
            return None
        return AccessToken(token=token, client_id="joinhound", scopes=[])

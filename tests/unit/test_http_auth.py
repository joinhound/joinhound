# SPDX-License-Identifier: Apache-2.0

"""HTTP transport refuses a request that has no bearer token."""

from starlette.testclient import TestClient

from joinhound.core.config import EngineConfig
from joinhound.server import Runtime, create_server

_TOKEN = "dev-token"


def test_http_rejects_a_request_without_a_token() -> None:
    app = _app()
    with TestClient(app) as client:
        missing = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        wrong = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Authorization": "Bearer other"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_http_accepts_the_configured_token() -> None:
    app = _app()
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={
                "Authorization": f"Bearer {_TOKEN}",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert response.status_code != 401


def _app() -> object:
    server = create_server(
        Runtime(engine=EngineConfig(), sources=[], links=[]),
        auth_token=_TOKEN,
    )
    return server.streamable_http_app()

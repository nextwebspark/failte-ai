from __future__ import annotations

from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.conftest import create_echo_connection, internal_headers, issue_key

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def mcp_client(app: FastAPI, url: str, key: str) -> Client[Any]:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.AsyncClient:
        # Redirects are deliberately not followed: both /mcp/<id> and
        # /mcp/<id>/ must be served directly.
        del follow_redirects
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=False,
        )

    return Client(StreamableHttpTransport(url, auth=key, httpx_client_factory=factory))


async def initialize(client: httpx.AsyncClient, path: str, key: str) -> int:
    response = await client.post(
        path,
        json=INITIALIZE,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {key}"},
    )
    return response.status_code


@pytest.mark.parametrize("path", ["/mcp/echo", "/mcp/echo/"])
async def test_mcp_round_trip(
    app: FastAPI, client: httpx.AsyncClient, path: str
) -> None:
    connection_id = await create_echo_connection(client, org_id=7, api_key="k-7")
    key = await issue_key(client, connection_id, org_id=7)

    async with mcp_client(app, f"http://tools{path}", key) as mcp:
        tools = await mcp.list_tools()
        assert {tool.name for tool in tools} == {"echo", "whoami"}

        echoed = await mcp.call_tool("echo", {"text": "hello"})
        assert echoed.data == "hello (org=7, key=k-7)"

        who = await mcp.call_tool("whoami", {})
        assert who.data == {
            "org_id": 7,
            "connection_id": connection_id,
            "provider": "echo",
        }


async def test_mcp_requires_valid_key(client: httpx.AsyncClient) -> None:
    connection_id = await create_echo_connection(client)
    key = await issue_key(client, connection_id)

    assert await initialize(client, "/mcp/echo", key) == 200
    assert await initialize(client, "/mcp/echo", "ftk_" + "x" * 43) == 401
    assert await initialize(client, "/mcp/echo", "nonsense") == 401
    no_auth = await client.post("/mcp/echo", json=INITIALIZE, headers=MCP_HEADERS)
    assert no_auth.status_code == 401


async def test_key_for_one_provider_rejected_by_another(
    client: httpx.AsyncClient,
) -> None:
    connection_id = await create_echo_connection(client, provider="echo")
    key = await issue_key(client, connection_id)

    assert await initialize(client, "/mcp/echo", key) == 200
    assert await initialize(client, "/mcp/echo-b", key) == 401


async def test_revoked_connection_key_rejected(client: httpx.AsyncClient) -> None:
    connection_id = await create_echo_connection(client)
    key = await issue_key(client, connection_id)
    assert await initialize(client, "/mcp/echo", key) == 200

    await client.delete(
        f"/internal/connections/{connection_id}", headers=internal_headers()
    )
    assert await initialize(client, "/mcp/echo", key) == 401


async def test_unknown_provider_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/mcp/missing", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 404

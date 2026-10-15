from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import httpx
import pytest

from fallcha_tools.core.path_guard import PathGuardMiddleware, is_suspicious_path


@pytest.mark.parametrize(
    "raw",
    [
        b"/oauth/x/../internal/catalog",
        b"/..",
        b"/oauth/..",
        b"/oauth/google-calendar/%2e%2e/callback",
        b"/oauth/google-calendar/%2E%2e/callback",
        b"/oauth/%2e/callback",
        b"/oauth/..%2f..%2finternal/callback",
        b"/oauth/google-calendar%2Fcallback",
        b"/oauth/google-calendar%5ccallback",
        b"/oauth/google-calendar\\callback",
    ],
)
def test_suspicious_paths(raw: bytes) -> None:
    assert is_suspicious_path(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"/health",
        b"/oauth/google-calendar/callback",
        b"/mcp/google-calendar/",
        b"/v1/website-catalogue/product_search",
        b"/internal/connections/4f6c.../sync",
        b"/files/a..b",
        b"/files/.hidden",
    ],
)
def test_ordinary_paths(raw: bytes) -> None:
    assert not is_suspicious_path(raw)


async def _call(raw_path: bytes, query: bytes = b"") -> tuple[int, bool]:
    """Run the middleware on a raw ASGI scope: (status, reached inner app)."""
    reached = False
    sent: list[MutableMapping[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        nonlocal reached
        reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": raw_path.decode(),
        "raw_path": raw_path,
        "query_string": query,
        "headers": [],
    }
    await PathGuardMiddleware(inner)(scope, receive, send)
    return int(sent[0]["status"]), reached


async def test_dot_segment_in_raw_path_rejected_before_routing() -> None:
    # httpx normalises "..", so this goes through a raw ASGI scope.
    assert await _call(b"/oauth/x/../../internal/catalog") == (400, False)


async def test_dots_in_query_are_ignored() -> None:
    status, reached = await _call(
        b"/oauth/google-calendar/callback", b"state=a%2e%2e%2fb"
    )
    assert (status, reached) == (200, True)


async def test_non_http_scopes_pass_through() -> None:
    called = False

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        nonlocal called
        called = True

    await PathGuardMiddleware(inner)({"type": "lifespan"}, None, None)  # type: ignore[arg-type]
    assert called


@pytest.mark.parametrize(
    "path",
    [
        "/oauth/google-calendar/%2e%2e/callback",
        "/internal%2fcatalog",
        "/mcp/echo%2F..%2Finternal",
        "/oauth/echo%5Ccallback",
    ],
)
async def test_app_rejects_encoded_traversal(
    client: httpx.AsyncClient, path: str
) -> None:
    response = await client.get(path)
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid request path"}


async def test_app_still_serves_normal_paths(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).status_code == 200

"""Reject request paths that try to escape their route.

No route of this service uses dot segments, encoded dots, encoded slashes or
backslashes, so a request carrying any of them is malformed or probing (for
example ``/oauth/x/..%2f..%2finternal/...`` past a reverse proxy that only
forwards ``/oauth/*``). The reverse proxy already rebuilds a clean path; this
is defence in depth, applied to the raw path before routing.
"""

from __future__ import annotations

import json
import re

from starlette.types import ASGIApp, Receive, Scope, Send

# Case-insensitive: %2e / %2E (dot), %2f (slash), %5c (backslash), a literal
# backslash, or a ".." path segment.
_FORBIDDEN = re.compile(rb"%2e|%2f|%5c|\\|(?:^|/)\.\.(?:/|$)", re.IGNORECASE)
_BODY = json.dumps({"detail": "invalid request path"}).encode()


def is_suspicious_path(raw_path: bytes) -> bool:
    """True if ``raw_path`` (the undecoded path, without the query) has a
    dot segment, an encoded dot/slash/backslash or a backslash."""
    return _FORBIDDEN.search(raw_path) is not None


class PathGuardMiddleware:
    """Pure ASGI middleware (it never buffers bodies, so streaming MCP
    responses are untouched) answering 400 to suspicious paths."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw = scope.get("raw_path")
            path = raw if isinstance(raw, bytes) else str(scope["path"]).encode()
            # Some servers include the query in raw_path; only the path counts.
            if is_suspicious_path(path.split(b"?", 1)[0]):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 400,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(_BODY)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": _BODY})
                return
        await self.app(scope, receive, send)

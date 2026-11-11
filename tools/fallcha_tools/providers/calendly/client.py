"""A small client for the Calendly API v2 (``https://api.calendly.com``).

Requests only ever go to Calendly's API host: paths are built here from
ids, never taken from a caller or from a stored URI as is, so the
connection's token cannot be sent anywhere else. Neither tokens nor bodies
are logged; error details are reduced to field names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from loguru import logger
from pydantic import JsonValue

from fallcha_tools.core.errors import ToolsError
from fallcha_tools.core.oauth import OAuthReconnectRequired, OAuthRefreshFailed
from fallcha_tools.core.provider import OAuthAccess
from fallcha_tools.providers.calendly.settings import API_BASE

DEFAULT_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
# What a token needs, as Calendly names the scopes (an owner creating a
# personal access token ticks these).
SCOPES = (
    "users:read",
    "event_types:read",
    "availability:read",
    "scheduled_events:write",
)
_PLAN_WORDS = ("upgrade", "paid")


class CalendlyError(ToolsError):
    """A Calendly failure. The message is safe to show (no token, no body)."""


class CalendlyApiError(CalendlyError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        fields: tuple[str, ...] = (),
        plan_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        # Request fields Calendly said were wrong (e.g. "invitee.email").
        self.fields = fields
        # Calendly asked for a plan upgrade (its Scheduling API once needed one).
        self.plan_required = plan_required


class TokenSource(Protocol):
    async def token(self) -> str: ...

    async def rejected(self, token: str) -> str | None:
        """A replacement for a token Calendly refused, or None."""
        ...


@dataclass(frozen=True)
class StaticToken:
    """A personal access token: nothing to refresh."""

    value: str = field(repr=False)

    async def token(self) -> str:
        return self.value

    async def rejected(self, token: str) -> str | None:
        del token
        return None


@dataclass(frozen=True)
class OAuthToken:
    """An OAuth2 connection's access token, refreshed by the core."""

    oauth: OAuthAccess

    async def token(self) -> str:
        try:
            return (await self.oauth.access_token()).token
        except (OAuthReconnectRequired, OAuthRefreshFailed) as exc:
            raise CalendlyApiError(str(exc)) from None

    async def rejected(self, token: str) -> str | None:
        try:
            return (await self.oauth.access_token(rejected=token)).token
        except (OAuthReconnectRequired, OAuthRefreshFailed) as exc:
            raise CalendlyApiError(str(exc)) from None


def _error_parts(response: httpx.Response) -> tuple[str, tuple[str, ...]]:
    """Calendly's error message and the names of the fields it blames."""
    try:
        body = response.json()
    except ValueError:
        return "", ()
    if not isinstance(body, dict):
        return "", ()
    message = body.get("message")
    fields: list[str] = []
    for item in body.get("details") or []:
        if isinstance(item, dict) and isinstance(item.get("parameter"), str):
            fields.append(item["parameter"][:100])
    return (message if isinstance(message, str) else "")[:300], tuple(fields)


def _api_error(response: httpx.Response, what: str) -> CalendlyApiError:
    status = response.status_code
    message, fields = _error_parts(response)
    plan = status == 403 and any(w in message.lower() for w in _PLAN_WORDS)
    # Status and field names only: messages can echo what was sent.
    logger.info("Calendly {} -> {} {}", what, status, ",".join(fields))
    if status == 401:
        text = "Calendly did not accept the connection's token; connect it again"
    elif plan:
        text = "Calendly says this needs a different Calendly plan"
    elif status == 403:
        text = (
            "Calendly refused this; the token may be missing a permission "
            f"({', '.join(SCOPES)})"
        )
    elif status == 404:
        text = "Calendly could not find that; check the chosen event type"
    elif status == 429:
        text = "Calendly is limiting requests just now; please try again shortly"
    elif status >= 500:
        text = "Calendly is having problems; please try again shortly"
    else:
        text = "Calendly did not accept the request"
    return CalendlyApiError(text, status=status, fields=fields, plan_required=plan)


class CalendlyClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        tokens: TokenSource,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._http = http
        self._tokens = tokens
        self._timeout = timeout

    async def get(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: Mapping[str, JsonValue]) -> dict[str, Any]:
        return await self._request("POST", path, json=dict(body))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: dict[str, JsonValue] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/") or "//" in path or ".." in path:
            raise ValueError("bad Calendly path")
        what = f"{method} {path.split('?')[0]}"
        token = await self._tokens.token()
        for attempt in range(2):
            try:
                response = await self._http.request(
                    method,
                    f"{API_BASE}{path}",
                    params=params,
                    json=json,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=self._timeout,
                )
            except httpx.TimeoutException:
                raise CalendlyApiError("Calendly did not respond in time") from None
            except httpx.HTTPError as exc:
                logger.warning("Calendly {} failed: {}", what, type(exc).__name__)
                raise CalendlyApiError("Could not reach Calendly") from None
            if response.status_code == 401 and attempt == 0:
                fresh = await self._tokens.rejected(token)
                if fresh is not None and fresh != token:
                    token = fresh
                    continue
            if response.status_code >= 400:
                raise _api_error(response, what)
            try:
                body = response.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                raise CalendlyApiError("Calendly sent an unreadable answer")
            return body
        raise AssertionError("unreachable")

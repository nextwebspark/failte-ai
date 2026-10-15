"""Authenticated, time-boxed requests to Google REST APIs.

:class:`GoogleHttp` is the transport every Google provider's client builds
on: each request carries a fresh bearer token from the connection's
:class:`GoogleCredentialsSource`, uses a short timeout (voice calls cannot
wait), is retried once with a new token on 401, and every failure becomes a
:class:`GoogleApiError` with a speakable, secret-free message. Raw Google
bodies are never returned or logged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from fallcha_tools.providers.google_common.credentials import GoogleCredentialsSource
from fallcha_tools.providers.google_common.errors import GoogleApiError

DEFAULT_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
# Nothing was sent to Google yet, so retrying is always safe.
SIGN_IN_TOO_SLOW = "signing in to Google took too long; please try again"

# Repeated keys (e.g. ``ranges`` of values:batchGet) are given as a sequence.
QueryParams = Mapping[str, str | Sequence[str]]

_RATE_LIMIT_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
)


@dataclass(frozen=True, slots=True)
class Budget:
    """Time left for a sequence of requests that must not be cut off midway.

    Each request gets the remaining time as its timeout; callers check
    :meth:`allows_request` before starting another one.
    """

    deadline_at: float  # event-loop time
    min_seconds: float

    @classmethod
    def starting_now(cls, seconds: float, *, min_seconds: float = 0.0) -> Budget:
        return cls(
            deadline_at=asyncio.get_running_loop().time() + seconds,
            min_seconds=min_seconds,
        )

    def remaining(self) -> float:
        return self.deadline_at - asyncio.get_running_loop().time()

    def allows_request(self) -> bool:
        return self.remaining() >= self.min_seconds

    def timeout(self) -> httpx.Timeout:
        left = max(self.remaining(), 0.001)
        return httpx.Timeout(left, connect=min(2.0, left))


def path_segment(segment: str) -> str:
    """``segment`` percent-encoded for use as one URL path segment."""
    return quote(segment, safe="")


def google_reason(response: httpx.Response) -> str:
    """Google's machine-readable error reason (never the message)."""
    try:
        error = response.json().get("error", {})
        if isinstance(error, dict):
            errors = error.get("errors") or [{}]
            return str(errors[0].get("reason") or error.get("status") or "")
    except (ValueError, AttributeError, IndexError):
        pass
    return ""


@dataclass(frozen=True, slots=True)
class GoogleHttp:
    """Calls Google as one connection. ``account_hint`` (e.g. the service
    account's email) is only logged, never shown to a caller."""

    http: httpx.AsyncClient
    credentials: GoogleCredentialsSource
    account_hint: str | None = None
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)

    async def _send(
        self,
        method: str,
        url: str,
        scopes: Sequence[str],
        *,
        json: Mapping[str, Any] | None = None,
        params: QueryParams | None = None,
        budget: Budget | None = None,
    ) -> httpx.Response:
        response = await self._attempt(method, url, scopes, json, params, budget)
        if response.status_code == 401:
            # The cached token may have been revoked early: mint once more,
            # unless a budgeted call has no time left for a mint and a retry.
            self.credentials.invalidate(scopes)
            if budget is None or budget.allows_request():
                response = await self._attempt(
                    method, url, scopes, json, params, budget
                )
        return response

    async def _attempt(
        self,
        method: str,
        url: str,
        scopes: Sequence[str],
        json: Mapping[str, Any] | None,
        params: QueryParams | None,
        budget: Budget | None,
    ) -> httpx.Response:
        token = await self._token(scopes, budget)
        try:
            return await self.http.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
                timeout=budget.timeout() if budget is not None else self.timeout,
            )
        except httpx.TimeoutException:
            raise GoogleApiError(
                "Google did not respond in time", retryable=True
            ) from None
        except httpx.HTTPError:
            raise GoogleApiError("could not reach Google", retryable=True) from None

    async def _token(self, scopes: Sequence[str], budget: Budget | None) -> str:
        """An access token; within ``budget`` when one is given. A token
        refresh that outlives the budget keeps running (it is shielded) and
        serves the next call."""
        if budget is None:
            return await self.credentials.access_token(scopes)
        try:
            async with asyncio.timeout(max(budget.remaining(), 0.0)):
                token = await self.credentials.access_token(scopes)
        except TimeoutError:
            raise GoogleApiError(SIGN_IN_TOO_SLOW) from None
        if not budget.allows_request():
            raise GoogleApiError(SIGN_IN_TOO_SLOW)
        return token

    async def _json(
        self,
        method: str,
        url: str,
        scopes: Sequence[str],
        resource: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: QueryParams | None = None,
        missing_ok: bool = False,
        budget: Budget | None = None,
    ) -> dict[str, Any]:
        response = await self._send(
            method, url, scopes, json=json, params=params, budget=budget
        )
        if missing_ok and response.status_code in (404, 410):
            return {}
        if response.status_code >= 400:
            raise self._error(response, resource)
        return self._body(response)

    @staticmethod
    def _body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            raise GoogleApiError("Google returned an unreadable response") from None
        if not isinstance(body, dict):
            raise GoogleApiError("Google returned an unreadable response")
        return body

    def _error(self, response: httpx.Response, resource: str) -> GoogleApiError:
        status, reason = response.status_code, google_reason(response)
        logger.warning(
            "google api {} failed: {} {} (as {})",
            resource,
            status,
            reason,
            self.account_hint,
        )
        if status == 429 or reason in _RATE_LIMIT_REASONS:
            return GoogleApiError("Google is rate limiting requests; please try again")
        if status == 401:
            return GoogleApiError("Google rejected the connection's credentials")
        if status in (403, 404):
            return self._access_error(resource, not_found=status == 404)
        if status >= 500:
            return GoogleApiError("Google is temporarily unavailable; please try again")
        return GoogleApiError(f"Google rejected the {resource} request (HTTP {status})")

    def _shared_resource(self, resource: str) -> bool:
        """Whether ``resource`` is something an admin shares with the
        connection's account (so "not accessible" may mean "not shared")."""
        del resource
        return True

    def _access_error(self, resource: str, *, not_found: bool) -> GoogleApiError:
        problem = "was not found" if not_found else "is not accessible"
        if not self._shared_resource(resource):
            return GoogleApiError(f"the {resource} {problem}")
        # Callers never see which Google account is used; admins get it from
        # the connection test.
        bare = f"the {resource} {problem}"
        return GoogleApiError(
            f"{bare}; it may not be shared with this connection",
            access_problem=bare,
        )

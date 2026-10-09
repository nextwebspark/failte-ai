"""Thin, typed wrappers over the Google Calendar and Sheets REST APIs.

Each request uses a short timeout (voice calls cannot wait), and every
failure becomes a :class:`GoogleApiError` with a speakable, secret-free
message. Raw Google bodies are never returned or logged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger
from pydantic import JsonValue

from fallcha_tools.providers.google_calendar.credentials import GoogleCredentialsSource
from fallcha_tools.providers.google_calendar.errors import GoogleApiError

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
# Read-only on purpose: the agent must never be able to change an order.
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"

DEFAULT_TIMEOUT = httpx.Timeout(4.0, connect=2.0)

_RATE_LIMIT_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
)


class Resource(StrEnum):
    CALENDAR = "calendar"
    EVENT = "appointment"
    SHEET = "orders sheet"


Busy = tuple[datetime, datetime]


@dataclass(frozen=True, slots=True)
class Budget:
    """Time left for a sequence of requests that must not be cut off midway.

    Each request gets the remaining time as its timeout; callers check
    :meth:`allows_request` before starting another one.
    """

    deadline_at: float  # event-loop time
    min_seconds: float

    def remaining(self) -> float:
        return self.deadline_at - asyncio.get_running_loop().time()

    def allows_request(self) -> bool:
        return self.remaining() >= self.min_seconds

    def timeout(self) -> httpx.Timeout:
        left = max(self.remaining(), 0.001)
        return httpx.Timeout(left, connect=min(2.0, left))


def _path(segment: str) -> str:
    return quote(segment, safe="")


def _reason(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        if isinstance(error, dict):
            errors = error.get("errors") or [{}]
            return str(errors[0].get("reason") or error.get("status") or "")
    except (ValueError, AttributeError, IndexError):
        pass
    return ""


@dataclass(frozen=True, slots=True)
class GoogleClient:
    """Calls Google as one connection. ``account_hint`` (e.g. the service
    account's email) is only logged; see ``CalendarService.check_access``."""

    http: httpx.AsyncClient
    credentials: GoogleCredentialsSource
    account_hint: str | None = None
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)

    async def free_busy(
        self, calendar_id: str, start: datetime, end: datetime, timezone: str
    ) -> list[Busy]:
        body = await self._json(
            "POST",
            f"{CALENDAR_API}/freeBusy",
            (CALENDAR_SCOPE,),
            Resource.CALENDAR,
            json={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": timezone,
                "items": [{"id": calendar_id}],
            },
        )
        entry = (body.get("calendars") or {}).get(calendar_id) or {}
        if entry.get("errors"):
            reasons = {str(e.get("reason", "")) for e in entry["errors"]}
            logger.warning(
                "google freeBusy calendar errors: {} (as {})",
                sorted(reasons),
                self.account_hint,
            )
            raise self._access_error(Resource.CALENDAR, not_found="notFound" in reasons)
        try:
            return [
                (
                    datetime.fromisoformat(block["start"]),
                    datetime.fromisoformat(block["end"]),
                )
                for block in entry.get("busy", [])
            ]
        except (KeyError, TypeError, ValueError):
            raise GoogleApiError("Google returned unreadable free/busy data") from None

    async def insert_event(
        self,
        calendar_id: str,
        event: Mapping[str, JsonValue],
        *,
        budget: Budget | None = None,
    ) -> bool:
        """Insert ``event`` (which carries a client-chosen ``id``).

        True if created now; False if an event with that id already exists
        (Google answers 409), which makes retries idempotent.
        """
        response = await self._send(
            "POST",
            f"{CALENDAR_API}/calendars/{_path(calendar_id)}/events",
            (CALENDAR_SCOPE,),
            json=dict(event),
            budget=budget,
        )
        if response.status_code == 409:
            return False
        if response.status_code >= 400:
            raise self._error(response, Resource.CALENDAR)
        return True

    async def restore_event(
        self,
        calendar_id: str,
        event: Mapping[str, JsonValue],
        *,
        budget: Budget | None = None,
    ) -> None:
        """Re-confirm a cancelled event with ``event``'s id and contents."""
        event_id = str(event["id"])
        response = await self._send(
            "PATCH",
            self._event_url(calendar_id, event_id),
            (CALENDAR_SCOPE,),
            json={**event, "status": "confirmed"},
            budget=budget,
        )
        if response.status_code >= 400:
            raise self._error(response, Resource.EVENT)

    async def get_event(
        self, calendar_id: str, event_id: str, *, budget: Budget | None = None
    ) -> dict[str, Any] | None:
        """The event, or None if it does not exist (or was deleted)."""
        body = await self._json(
            "GET",
            self._event_url(calendar_id, event_id),
            (CALENDAR_SCOPE,),
            Resource.EVENT,
            missing_ok=True,
            budget=budget,
        )
        return body or None

    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """True if deleted now; False if it was already gone."""
        response = await self._send(
            "DELETE",
            self._event_url(calendar_id, event_id),
            (CALENDAR_SCOPE,),
            params={"sendUpdates": "none"},
        )
        if response.status_code in (404, 410):
            return False
        if response.status_code >= 400:
            raise self._error(response, Resource.EVENT)
        return True

    async def calendar_summary(self, calendar_id: str) -> str:
        body = await self._json(
            "GET",
            f"{CALENDAR_API}/calendars/{_path(calendar_id)}",
            (CALENDAR_SCOPE,),
            Resource.CALENDAR,
        )
        return str(body.get("summary") or calendar_id)

    async def sheet_values(self, sheet_id: str, a1_range: str) -> list[list[str]]:
        body = await self._json(
            "GET",
            f"{SHEETS_API}/{_path(sheet_id)}/values/{_path(a1_range)}",
            (SHEETS_READONLY_SCOPE,),
            Resource.SHEET,
        )
        values = body.get("values") or []
        return [[str(cell) for cell in row] for row in values if isinstance(row, list)]

    async def sheet_title(self, sheet_id: str) -> str:
        body = await self._json(
            "GET",
            f"{SHEETS_API}/{_path(sheet_id)}",
            (SHEETS_READONLY_SCOPE,),
            Resource.SHEET,
            params={"fields": "properties.title"},
        )
        return str((body.get("properties") or {}).get("title") or sheet_id)

    def _event_url(self, calendar_id: str, event_id: str) -> str:
        return f"{CALENDAR_API}/calendars/{_path(calendar_id)}/events/{_path(event_id)}"

    async def _send(
        self,
        method: str,
        url: str,
        scopes: Sequence[str],
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
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
        params: Mapping[str, str] | None,
        budget: Budget | None,
    ) -> httpx.Response:
        token = await self.credentials.access_token(scopes)
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

    async def _json(
        self,
        method: str,
        url: str,
        scopes: Sequence[str],
        resource: Resource,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
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
        try:
            body = response.json()
        except ValueError:
            raise GoogleApiError("Google returned an unreadable response") from None
        if not isinstance(body, dict):
            raise GoogleApiError("Google returned an unreadable response")
        return body

    def _error(self, response: httpx.Response, resource: Resource) -> GoogleApiError:
        status, reason = response.status_code, _reason(response)
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

    def _access_error(self, resource: Resource, *, not_found: bool) -> GoogleApiError:
        problem = "was not found" if not_found else "is not accessible"
        if resource == Resource.EVENT:
            return GoogleApiError(f"the {resource} {problem}")
        # Callers never see which Google account is used; admins get it from
        # the connection test (see CalendarService.check_access).
        bare = f"the {resource} {problem}"
        return GoogleApiError(
            f"{bare}; it may not be shared with this connection",
            access_problem=bare,
        )

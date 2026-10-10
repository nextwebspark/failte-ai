"""Thin, typed wrappers over the Google Calendar and Sheets REST APIs.

The transport (tokens, timeouts, error mapping) is the shared
:class:`~fallcha_tools.providers.google_common.http.GoogleHttp`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from loguru import logger
from pydantic import JsonValue

from fallcha_tools.providers.google_common.errors import GoogleApiError
from fallcha_tools.providers.google_common.http import (
    DEFAULT_TIMEOUT,
    SIGN_IN_TOO_SLOW,
    Budget,
    GoogleHttp,
    path_segment,
)
from fallcha_tools.providers.google_common.scopes import (
    CALENDAR_API,
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    CALENDAR_SCOPE,
    SHEETS_API,
    SHEETS_READONLY_SCOPE,
    SHEETS_SCOPE,
)

__all__ = [
    "CALENDAR_API",
    "CALENDAR_EVENTS_SCOPE",
    "CALENDAR_READONLY_SCOPE",
    "CALENDAR_SCOPE",
    "DEFAULT_TIMEOUT",
    "SHEETS_API",
    "SHEETS_READONLY_SCOPE",
    "SHEETS_SCOPE",
    "SIGN_IN_TOO_SLOW",
    "Budget",
    "Busy",
    "GoogleClient",
    "Resource",
]

# The orders sheet is read with the read-only scope on purpose: the agent
# must never be able to change an order.


class Resource(StrEnum):
    CALENDAR = "calendar"
    EVENT = "appointment"
    SHEET = "orders sheet"


Busy = tuple[datetime, datetime]


@dataclass(frozen=True, slots=True)
class GoogleClient(GoogleHttp):
    """Calendar and Sheets calls as one connection. ``account_hint`` is only
    logged; see ``CalendarService.check_access``."""

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
            f"{CALENDAR_API}/calendars/{path_segment(calendar_id)}/events",
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
            f"{CALENDAR_API}/calendars/{path_segment(calendar_id)}",
            (CALENDAR_SCOPE,),
            Resource.CALENDAR,
        )
        return str(body.get("summary") or calendar_id)

    async def sheet_values(self, sheet_id: str, a1_range: str) -> list[list[str]]:
        body = await self._json(
            "GET",
            f"{SHEETS_API}/{path_segment(sheet_id)}/values/{path_segment(a1_range)}",
            (SHEETS_READONLY_SCOPE,),
            Resource.SHEET,
        )
        values = body.get("values") or []
        return [[str(cell) for cell in row] for row in values if isinstance(row, list)]

    async def sheet_title(self, sheet_id: str) -> str:
        body = await self._json(
            "GET",
            f"{SHEETS_API}/{path_segment(sheet_id)}",
            (SHEETS_READONLY_SCOPE,),
            Resource.SHEET,
            params={"fields": "properties.title"},
        )
        return str((body.get("properties") or {}).get("title") or sheet_id)

    def _event_url(self, calendar_id: str, event_id: str) -> str:
        calendar = path_segment(calendar_id)
        return f"{CALENDAR_API}/calendars/{calendar}/events/{path_segment(event_id)}"

    def _shared_resource(self, resource: str) -> bool:
        # An event is not shared on its own: "not found" just means gone.
        return resource != Resource.EVENT

"""Test doubles for Outlook Calendar: an in-memory Microsoft Graph calendar
behind respx routes, and a stand-in for a connection's OAuth tokens."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx
import respx

from fallcha_tools.core.provider import AccessToken
from fallcha_tools.providers.outlook_calendar.auth import GRAPH_API

ME = f"{GRAPH_API}/me"
_PROPERTY_FILTER = re.compile(
    r"ep/id eq '((?:[^']|'')*)' and ep/value eq '((?:[^']|'')*)'"
)


def graph_time(value: datetime) -> dict[str, str]:
    """How Graph returns a time with ``Prefer: outlook.timezone="UTC"``."""
    naive = value.astimezone(UTC).replace(tzinfo=None)
    return {"dateTime": naive.isoformat() + ".0000000", "timeZone": "UTC"}


def _parse(value: str) -> datetime:
    text = re.sub(r"\.\d+", "", value)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class FakeTokens:
    """:class:`~fallcha_tools.core.provider.OAuthAccess` handing out one token."""

    token: str = "EwB-graph-access-token"
    calls: int = 0

    async def access_token(self, *, rejected: str | None = None) -> AccessToken:
        self.calls += 1
        if rejected == self.token:
            self.token += "-new"
        return AccessToken(self.token, datetime.now(UTC) + timedelta(hours=1))


@dataclass
class FakeGraph:
    """One mailbox's default calendar. ``events`` holds Graph event bodies
    by Graph id, as Graph would return them (all extended properties)."""

    router: respx.MockRouter
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    created: int = 0

    def __post_init__(self) -> None:
        r = self.router
        self.calendar = r.get(f"{ME}/calendar").mock(
            return_value=httpx.Response(200, json={"id": "cal-1", "name": "Calendar"})
        )
        self.view = r.get(f"{ME}/calendar/calendarView").mock(side_effect=self._view)
        self.search = r.get(f"{ME}/calendar/events").mock(side_effect=self._search)
        self.insert = r.post(f"{ME}/calendar/events").mock(side_effect=self._insert)
        self.delete = r.delete(url__regex=rf"^{re.escape(ME)}/events/[^/]+$").mock(
            side_effect=self._delete
        )
        self.patch = r.patch(url__regex=rf"^{re.escape(ME)}/events/[^/]+$").mock(
            side_effect=self._patch
        )

    def add(
        self,
        start: datetime,
        end: datetime,
        *,
        subject: str = "Staff meeting",
        show_as: str = "busy",
        all_day: bool = False,
        **extra: Any,
    ) -> str:
        """An event someone added in Outlook; returns its Graph id."""
        graph_id = f"AAMk-{len(self.events) + 1}"
        self.events[graph_id] = {
            "id": graph_id,
            "subject": subject,
            "body": {"contentType": "text", "content": ""},
            "start": graph_time(start),
            "end": graph_time(end),
            "showAs": show_as,
            "isAllDay": all_day,
            "isCancelled": False,
            "createdDateTime": self.now.isoformat().replace("+00:00", "Z"),
            **extra,
        }
        return graph_id

    def ours(self) -> list[dict[str, Any]]:
        return [
            e for e in self.events.values() if e.get("singleValueExtendedProperties")
        ]

    def _view(self, request: httpx.Request) -> httpx.Response:
        start = _parse(request.url.params["startDateTime"])
        end = _parse(request.url.params["endDateTime"])
        found = [
            e
            for e in self.events.values()
            if _parse(e["start"]["dateTime"]) < end
            and _parse(e["end"]["dateTime"]) > start
        ]
        found.sort(key=lambda e: e["start"]["dateTime"])
        return httpx.Response(200, json={"value": found})

    def _search(self, request: httpx.Request) -> httpx.Response:
        match = _PROPERTY_FILTER.search(unquote(request.url.params["$filter"]))
        assert match is not None, request.url.params["$filter"]
        prop_id, value = (g.replace("''", "'") for g in match.groups())
        found = [
            e
            for e in self.events.values()
            if any(
                p["id"].lower() == prop_id.lower() and p["value"] == value
                for p in e.get("singleValueExtendedProperties", [])
            )
        ]
        return httpx.Response(200, json={"value": found})

    def _insert(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.created += 1
        graph_id = f"AAMk-booked-{self.created}"
        event = {
            **body,
            "id": graph_id,
            "start": {
                "dateTime": body["start"]["dateTime"] + ".0000000",
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": body["end"]["dateTime"] + ".0000000",
                "timeZone": "UTC",
            },
            "isAllDay": False,
            "isCancelled": False,
            # Outlook hands text bodies back with Windows line endings.
            "body": {
                "contentType": "text",
                "content": body["body"]["content"].replace("\n", "\r\n") + "\r\n",
            },
            "createdDateTime": self.now.isoformat().replace("+00:00", "Z"),
        }
        self.events[graph_id] = event
        return httpx.Response(201, json=event)

    def _graph_id(self, request: httpx.Request) -> str:
        return unquote(request.url.path.rsplit("/", 1)[1])

    def _delete(self, request: httpx.Request) -> httpx.Response:
        if self.events.pop(self._graph_id(request), None) is None:
            return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
        return httpx.Response(204)

    def _patch(self, request: httpx.Request) -> httpx.Response:
        event = self.events.get(self._graph_id(request))
        if event is None:
            return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
        event.update(json.loads(request.content))
        return httpx.Response(200, json=event)

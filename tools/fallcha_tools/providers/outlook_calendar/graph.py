"""Outlook Calendar through Microsoft Graph, on the calendar service's model.

:class:`GraphCalendarClient` makes the calls
:class:`~fallcha_tools.providers.google_calendar.service.CalendarBackend`
describes, so the booking rules, slot finding, caller matching and spoken
answers are the Google Calendar provider's, unchanged. What differs:

- Graph picks its own event ids. A booking's id (the deterministic HMAC the
  service chooses, see ``booking_event_id``) is stored on the event as a
  single-value extended property, next to the service's private properties
  (connection marker, phone key, party size); every lookup by booking id
  filters on it. An insert first looks the id up, which keeps a retried
  booking from being made twice.
- Free/busy is read from ``calendarView``: every event not shown as Free (or
  "working elsewhere") blocks its time, as Outlook's own scheduling does.
- Deleting an Outlook event removes it, so the bookings list shows cancelled
  bookings only while Outlook still marks them cancelled.

Times are read in UTC (``Prefer: outlook.timezone="UTC"``) and written in
UTC; bodies are read and written as plain text. Raw Graph bodies are never
returned or logged, and every failure is a speakable ``GoogleApiError`` (the
calendar service's shared error class).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from loguru import logger
from pydantic import JsonValue

from fallcha_tools.providers.google_calendar.client import Budget, Busy, Resource
from fallcha_tools.providers.google_calendar.matching import PHONE_KEY_PROPERTY
from fallcha_tools.providers.google_calendar.service import (
    BOOKING_MARKER,
    PARTY_SIZE_PROP,
)
from fallcha_tools.providers.google_common.credentials import GoogleCredentialsSource
from fallcha_tools.providers.google_common.errors import GoogleApiError
from fallcha_tools.providers.google_common.http import DEFAULT_TIMEOUT, path_segment
from fallcha_tools.providers.outlook_calendar.auth import CALENDARS_SCOPE, GRAPH_API

# The extended-property namespace of LightMove bookings (a fixed GUID: it
# must never change, or earlier bookings would no longer be found).
PROPERTY_SET = "{4b1c9d0e-6f2a-4c38-9a57-1d8e3b6f2c41}"
# The booking id the service chose (Graph's own id is kept apart).
BOOKING_ID_PROP = "fallcha_booking_id"
PRIVATE_PROPS = (BOOKING_ID_PROP, BOOKING_MARKER, PHONE_KEY_PROPERTY, PARTY_SIZE_PROP)
# The connection's default calendar.
PRIMARY = "primary"
SCOPES = (CALENDARS_SCOPE,)
EVENT_FIELDS = "id,subject,body,start,end,showAs,isAllDay,isCancelled,createdDateTime"
PAGE_SIZE = 250
MAX_PAGES = 8
# Free/busy: these "show as" values leave the time open.
_OPEN_SHOW_AS = frozenset({"free", "workingElsewhere"})
_FRACTION = re.compile(r"\.(\d+)")


def property_id(name: str) -> str:
    return f"String {PROPERTY_SET} Name {name}"


def _expand() -> str:
    wanted = " or ".join(f"id eq '{property_id(name)}'" for name in PRIVATE_PROPS)
    return f"singleValueExtendedProperties($filter={wanted})"


def _quoted(value: str) -> str:
    """An OData string literal."""
    return "'" + value.replace("'", "''") + "'"


def _property_filter(name: str, value: str) -> str:
    return (
        "singleValueExtendedProperties/Any(ep: ep/id eq "
        f"{_quoted(property_id(name))} and ep/value eq {_quoted(value)})"
    )


def _parse_time(raw: object, zone_name: object = "UTC") -> datetime | None:
    """A Graph timestamp (up to 7 fraction digits, maybe without an offset;
    ``zone_name`` then says which zone it is in)."""
    if not isinstance(raw, str):
        return None
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), raw, count=1)
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        try:
            zone: Any = (
                UTC if zone_name in (None, "", "UTC") else ZoneInfo(str(zone_name))
            )
        except (ZoneInfoNotFoundError, ValueError):
            zone = UTC
        value = value.replace(tzinfo=zone)
    return value


def _graph_time(value: object, all_day: bool) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    if all_day:
        raw = value.get("dateTime")
        return {"date": raw[:10]} if isinstance(raw, str) and len(raw) >= 10 else None
    parsed = _parse_time(value.get("dateTime"), value.get("timeZone"))
    return {"dateTime": parsed.isoformat()} if parsed is not None else None


def _properties(event: Mapping[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    prefix = f"string {PROPERTY_SET} name ".lower()
    for prop in event.get("singleValueExtendedProperties") or ():
        if not isinstance(prop, Mapping):
            continue
        prop_id, value = prop.get("id"), prop.get("value")
        if (
            isinstance(prop_id, str)
            and isinstance(value, str)
            and prop_id.lower().startswith(prefix)
        ):
            found[prop_id[len(prefix) :]] = value
    return found


def _text_body(event: Mapping[str, Any]) -> str:
    body = event.get("body")
    content = body.get("content") if isinstance(body, Mapping) else None
    if not isinstance(content, str):
        return ""
    lines = [line.strip() for line in content.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def to_calendar_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """A Graph event as the calendar service reads events (Google's shape),
    or None when it has no usable id or times."""
    graph_id = event.get("id")
    if not isinstance(graph_id, str) or not graph_id:
        return None
    all_day = event.get("isAllDay") is True
    start = _graph_time(event.get("start"), all_day)
    end = _graph_time(event.get("end"), all_day)
    if start is None or end is None:
        return None
    private = _properties(event)
    booking_id = private.pop(BOOKING_ID_PROP, None)
    created = _parse_time(event.get("createdDateTime"))
    converted: dict[str, Any] = {
        "id": booking_id or graph_id,
        "graph_id": graph_id,
        "status": "cancelled" if event.get("isCancelled") is True else "confirmed",
        "summary": str(event.get("subject") or ""),
        "description": _text_body(event),
        "start": start,
        "end": end,
        "extendedProperties": {"private": private},
    }
    if created is not None:
        converted["created"] = created.isoformat()
    if event.get("showAs") in _OPEN_SHOW_AS:
        converted["transparency"] = "transparent"
    return converted


def _utc_time(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise GoogleApiError("the appointment has no time")
    parsed = _parse_time(value.get("dateTime"))
    if parsed is None:
        raise GoogleApiError("the appointment has no time")
    naive = parsed.astimezone(UTC).replace(tzinfo=None)
    return {"dateTime": naive.isoformat(timespec="seconds"), "timeZone": "UTC"}


def to_graph_event(event: Mapping[str, JsonValue]) -> dict[str, Any]:
    """The service's event (Google's shape) as a Graph event body."""
    props = event.get("extendedProperties")
    private = props.get("private") if isinstance(props, Mapping) else None
    values: dict[str, str] = {BOOKING_ID_PROP: str(event["id"])}
    if isinstance(private, Mapping):
        values.update(
            {k: str(v) for k, v in private.items() if k in PRIVATE_PROPS and v}
        )
    return {
        "subject": str(event.get("summary") or ""),
        "body": {"contentType": "text", "content": str(event.get("description") or "")},
        "start": _utc_time(event.get("start")),
        "end": _utc_time(event.get("end")),
        "showAs": "busy",
        "isReminderOn": False,
        "singleValueExtendedProperties": [
            {"id": property_id(name), "value": value} for name, value in values.items()
        ],
    }


def _error_code(response: httpx.Response) -> str:
    """Graph's machine-readable error code (never the message)."""
    try:
        error = response.json().get("error", {})
        if isinstance(error, dict):
            return str(error.get("code") or "")[:64]
    except (ValueError, AttributeError):
        pass
    return ""


@dataclass(frozen=True, slots=True)
class GraphCalendarClient:
    """Outlook calendar calls as one connection. ``account_hint`` (the
    connected account's address) is only logged and shown to admins."""

    http: httpx.AsyncClient
    credentials: GoogleCredentialsSource
    account_hint: str | None = None
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)

    # -- the CalendarBackend calls --------------------------------------------

    async def free_busy(
        self, calendar_id: str, start: datetime, end: datetime, timezone: str
    ) -> list[Busy]:
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        busy: list[Busy] = []
        for event in await self.list_events(calendar_id, start, end):
            if event.get("status") == "cancelled" or event.get("transparency"):
                continue
            span = _span(event, zone)
            if span is not None:
                busy.append(span)
        return busy

    async def list_events(
        self,
        calendar_id: str,
        start: datetime,
        end: datetime,
        *,
        show_deleted: bool = False,
        private_property: str | None = None,
        budget: Budget | None = None,
    ) -> list[dict[str, Any]]:
        """Events overlapping [start, end), recurring ones expanded, oldest
        first. Deleted Outlook events are gone, so ``show_deleted`` adds
        nothing. ``private_property`` ("key=value") keeps only events
        carrying it."""
        del show_deleted
        events = await self._calendar_view(
            calendar_id, start, end, PAGE_SIZE, MAX_PAGES, budget, partial_ok=False
        )
        if private_property:
            name, _, value = private_property.partition("=")
            events = [e for e in events if _private(e).get(name) == value]
        return events

    async def insert_event(
        self,
        calendar_id: str,
        event: Mapping[str, JsonValue],
        *,
        budget: Budget | None = None,
    ) -> bool:
        """Create ``event``. False when an event with its booking id is
        already on the calendar (a retry of a booking that went through)."""
        booking_id = str(event["id"])
        if await self._find(calendar_id, booking_id, budget=budget) is not None:
            return False
        if budget is not None and not budget.allows_request():
            raise GoogleApiError("no time left to book", retryable=True)
        response = await self._send(
            "POST",
            f"{self._calendar_url(calendar_id)}/events",
            json=to_graph_event(event),
            budget=budget,
        )
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
        """Put ``event`` back as it was booked (or create it again)."""
        found = await self._find(calendar_id, str(event["id"]), budget=budget)
        body = to_graph_event(event)
        if found is None:
            url, method = f"{self._calendar_url(calendar_id)}/events", "POST"
        else:
            url, method = self._event_url(found["graph_id"]), "PATCH"
        response = await self._send(method, url, json=body, budget=budget)
        if response.status_code >= 400:
            raise self._error(response, Resource.EVENT)

    async def get_event(
        self, calendar_id: str, event_id: str, *, budget: Budget | None = None
    ) -> dict[str, Any] | None:
        return await self._find(calendar_id, event_id, budget=budget)

    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        found = await self._find(calendar_id, event_id)
        if found is None:
            return False
        response = await self._send("DELETE", self._event_url(found["graph_id"]))
        if response.status_code in (404, 410):
            return False
        if response.status_code >= 400:
            raise self._error(response, Resource.EVENT)
        return True

    async def list_tagged_events(
        self,
        calendar_id: str,
        *,
        private_properties: Mapping[str, str],
        time_min: datetime,
        time_max: datetime,
        page_size: int,
        max_pages: int = 1,
        budget: Budget | None = None,
    ) -> list[dict[str, Any]]:
        """Events (not cancelled) carrying every ``private_properties`` entry
        that end after ``time_min`` and start before ``time_max``, soonest
        first.

        A lookup by something other than the connection marker (the
        caller's phone key) is filtered by Graph on that property, so a
        busy diary cannot push the caller's bookings off the page; a lookup
        by the marker alone reads the time range with ``calendarView``."""
        selective = next((k for k in private_properties if k != BOOKING_MARKER), None)
        if selective is None:
            events = await self._calendar_view(
                calendar_id,
                time_min,
                time_max,
                page_size,
                max_pages,
                budget,
                partial_ok=True,
            )
        else:
            events = await self._filtered(
                calendar_id,
                _property_filter(selective, private_properties[selective]),
                page_size,
                max_pages,
                budget,
            )
        kept = []
        for event in events:
            span = _span(event, UTC)
            props = _private(event)
            if (
                event.get("status") != "cancelled"
                and span is not None
                and span[1] > time_min
                and span[0] < time_max
                and all(props.get(k) == v for k, v in private_properties.items())
            ):
                kept.append((span[0], event))
        kept.sort(key=lambda item: item[0])
        return [event for _, event in kept]

    async def calendar_summary(self, calendar_id: str) -> str:
        response = await self._send("GET", self._calendar_url(calendar_id))
        if response.status_code >= 400:
            raise self._error(response, Resource.CALENDAR)
        name = self._body(response).get("name")
        return str(name) if name else "Calendar"

    # -- reads ----------------------------------------------------------------

    async def _find(
        self, calendar_id: str, booking_id: str, *, budget: Budget | None = None
    ) -> dict[str, Any] | None:
        """The event booked with ``booking_id``, or None."""
        if not booking_id.strip() or len(booking_id) > 200:
            return None
        events = await self._filtered(
            calendar_id, _property_filter(BOOKING_ID_PROP, booking_id), 2, 1, budget
        )
        return next((e for e in events if e.get("id") == booking_id), None)

    async def _filtered(
        self,
        calendar_id: str,
        odata_filter: str,
        page_size: int,
        max_pages: int,
        budget: Budget | None,
    ) -> list[dict[str, Any]]:
        params = {
            "$filter": odata_filter,
            "$top": str(page_size),
            "$select": EVENT_FIELDS,
            "$expand": _expand(),
        }
        return await self._pages(
            f"{self._calendar_url(calendar_id)}/events",
            params,
            max_pages,
            budget,
            partial_ok=True,
        )

    async def _calendar_view(
        self,
        calendar_id: str,
        start: datetime,
        end: datetime,
        page_size: int,
        max_pages: int,
        budget: Budget | None,
        *,
        partial_ok: bool,
    ) -> list[dict[str, Any]]:
        params = {
            "startDateTime": start.astimezone(UTC).isoformat(),
            "endDateTime": end.astimezone(UTC).isoformat(),
            "$top": str(page_size),
            "$orderby": "start/dateTime",
            "$select": EVENT_FIELDS,
            "$expand": _expand(),
        }
        return await self._pages(
            f"{self._calendar_url(calendar_id)}/calendarView",
            params,
            max_pages,
            budget,
            partial_ok=partial_ok,
        )

    async def _pages(
        self,
        url: str,
        params: Mapping[str, str],
        max_pages: int,
        budget: Budget | None,
        *,
        partial_ok: bool,
    ) -> list[dict[str, Any]]:
        """Up to ``max_pages`` pages, following ``@odata.nextLink``. Without
        ``partial_ok`` running out of pages is an error (capacity is never
        counted from a partial list); with it, the events read so far are
        returned, also when a ``budget`` allows no further page."""
        events: list[dict[str, Any]] = []
        next_url: str | None = url
        query: Mapping[str, str] | None = params
        for page in range(max_pages):
            if page and budget is not None and not budget.allows_request():
                break
            assert next_url is not None
            response = await self._send("GET", next_url, params=query, budget=budget)
            if response.status_code >= 400:
                raise self._error(response, Resource.CALENDAR)
            body = self._body(response)
            items = body.get("value", [])
            if not isinstance(items, list):
                raise GoogleApiError("Microsoft returned an unreadable event list")
            for item in items:
                if isinstance(item, dict):
                    converted = to_calendar_event(item)
                    if converted is not None:
                        events.append(converted)
            link = body.get("@odata.nextLink")
            if not isinstance(link, str) or not link.startswith(GRAPH_API):
                return events
            # The next link carries the whole query.
            next_url, query = link, None
        if partial_ok:
            logger.info("graph events stopped after {} event(s)", len(events))
            return events
        raise GoogleApiError("The calendar has too many events in that range to read")

    # -- transport ------------------------------------------------------------

    def _calendar_url(self, calendar_id: str) -> str:
        if calendar_id == PRIMARY:
            return f"{GRAPH_API}/me/calendar"
        return f"{GRAPH_API}/me/calendars/{path_segment(calendar_id)}"

    @staticmethod
    def _event_url(graph_id: str) -> str:
        return f"{GRAPH_API}/me/events/{path_segment(graph_id)}"

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        budget: Budget | None = None,
    ) -> httpx.Response:
        response = await self._attempt(method, url, json, params, budget)
        if response.status_code == 401:
            # The cached token may have been revoked early: get a new one once.
            self.credentials.invalidate(SCOPES)
            if budget is None or budget.allows_request():
                response = await self._attempt(method, url, json, params, budget)
        return response

    async def _attempt(
        self,
        method: str,
        url: str,
        json: Mapping[str, Any] | None,
        params: Mapping[str, str] | None,
        budget: Budget | None,
    ) -> httpx.Response:
        token = await self._token(budget)
        headers = [
            ("Authorization", f"Bearer {token}"),
            ("Prefer", 'outlook.timezone="UTC"'),
            ("Prefer", 'outlook.body-content-type="text"'),
        ]
        try:
            return await self.http.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=budget.timeout() if budget is not None else self.timeout,
            )
        except httpx.TimeoutException:
            raise GoogleApiError(
                "Microsoft did not respond in time", retryable=True
            ) from None
        except httpx.HTTPError:
            raise GoogleApiError("could not reach Microsoft", retryable=True) from None

    async def _token(self, budget: Budget | None) -> str:
        if budget is None:
            return await self.credentials.access_token(SCOPES)
        too_slow = "signing in to Microsoft took too long; please try again"
        try:
            async with asyncio.timeout(max(budget.remaining(), 0.0)):
                token = await self.credentials.access_token(SCOPES)
        except TimeoutError:
            raise GoogleApiError(too_slow) from None
        if not budget.allows_request():
            raise GoogleApiError(too_slow)
        return token

    @staticmethod
    def _body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            raise GoogleApiError("Microsoft returned an unreadable response") from None
        if not isinstance(body, dict):
            raise GoogleApiError("Microsoft returned an unreadable response")
        return body

    def _error(self, response: httpx.Response, resource: str) -> GoogleApiError:
        status, code = response.status_code, _error_code(response)
        logger.warning(
            "graph {} request failed: {} {} (as {})",
            resource,
            status,
            code,
            self.account_hint,
        )
        if status == 429:
            return GoogleApiError(
                "Microsoft is rate limiting requests; please try again"
            )
        if status == 401:
            return GoogleApiError("Microsoft rejected the connection's credentials")
        if status in (403, 404):
            problem = "was not found" if status == 404 else "is not accessible"
            bare = f"the {resource} {problem}"
            if resource == Resource.EVENT:
                return GoogleApiError(bare)
            return GoogleApiError(
                f"{bare} for the connected Microsoft account", access_problem=bare
            )
        if status >= 500:
            return GoogleApiError(
                "Microsoft is temporarily unavailable; please try again"
            )
        return GoogleApiError(
            f"Microsoft rejected the {resource} request (HTTP {status})"
        )


def _private(event: Mapping[str, Any]) -> Mapping[str, Any]:
    props = event.get("extendedProperties")
    private = props.get("private") if isinstance(props, Mapping) else None
    return private if isinstance(private, Mapping) else {}


def _span(event: Mapping[str, Any], zone: Any) -> Busy | None:
    start, end = event.get("start"), event.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return None
    try:
        if "dateTime" in start and "dateTime" in end:
            return (
                datetime.fromisoformat(start["dateTime"]),
                datetime.fromisoformat(end["dateTime"]),
            )
        first = datetime.fromisoformat(start["date"]).replace(tzinfo=zone)
        last = datetime.fromisoformat(end["date"]).replace(tzinfo=zone)
    except (KeyError, TypeError, ValueError):
        return None
    return first, max(last, first + timedelta(days=1))

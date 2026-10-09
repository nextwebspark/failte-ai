"""The calendar use cases, shared by the MCP tools and the REST routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from pydantic import JsonValue

from fallcha_tools.core.provider import ConnectionContext
from fallcha_tools.providers.google_calendar.client import GoogleClient
from fallcha_tools.providers.google_calendar.credentials import Clock
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    GoogleApiError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.orders import (
    SHEET_COLUMNS,
    OrdersCache,
    match_order,
    rows_from_values,
)
from fallcha_tools.providers.google_calendar.scheduling import (
    Busy,
    Window,
    bookable_window,
    free_slots,
    resolve_window,
)
from fallcha_tools.providers.google_calendar.schemas import (
    AvailabilityResult,
    BookingResult,
    CancelResult,
    OrderLookupResult,
    Slot,
)
from fallcha_tools.providers.google_calendar.settings import CalendarConfig
from fallcha_tools.providers.google_calendar.speech import join_spoken, say_time

# Events this service books carry the connection id here; cancel only
# touches events whose marker matches the calling connection.
BOOKING_MARKER = "fallcha_connection_id"
# Busy lookups for windows closer together than this share one freeBusy call.
MAX_FREEBUSY_SPAN = timedelta(days=60)
DEFAULT_DEADLINE_SECONDS = 5.0
CANCEL_NOT_FOUND = "I could not find that appointment to cancel."
# A booking insert is only started with at least this much deadline left.
DEFAULT_MIN_INSERT_SECONDS = 1.0
BAD_SLOT_ID = (
    "slot_id must be an ISO timestamp copied from check_appointment_availability"
)
UNCONFIRMED_BOOKING = (
    "Google did not confirm the booking in time; please try booking the same slot again"
)


def booking_event_id(
    connection_id: uuid.UUID, slot: datetime, caller_name: str, caller_phone: str
) -> str:
    """Deterministic Google event id (base32hex) for one booking request.

    Retrying the same booking re-sends the same id, so Google answers 409
    instead of creating a duplicate.
    """
    phone = "".join(ch for ch in caller_phone if ch.isdigit()) or caller_phone
    seed = "|".join(
        [str(connection_id), slot.isoformat(), caller_name.strip().lower(), phone]
    )
    digest = hashlib.sha256(seed.encode()).digest()
    return base64.b32hexencode(digest).decode().rstrip("=").lower()


def _slots(found: Sequence[datetime]) -> list[Slot]:
    return [Slot(id=slot.isoformat(), say=say_time(slot)) for slot in found]


def _a1_tab(tab: str) -> str:
    """A sheet tab name quoted for A1 notation (handles spaces and quotes)."""
    return "'" + tab.replace("'", "''") + "'"


@dataclass(frozen=True, slots=True)
class CalendarService:
    """One connection's calendar, with its booking rules."""

    client: GoogleClient
    config: CalendarConfig
    connection_id: uuid.UUID
    clock: Clock
    orders_cache: OrdersCache
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    min_insert_seconds: float = DEFAULT_MIN_INSERT_SECONDS

    async def availability(
        self, relative_day: str | None, part_of_day: str | None
    ) -> AvailabilityResult:
        cfg = self.config
        async with self._deadline():
            now = self._now()
            window = resolve_window(relative_day, now, cfg)
            wide = bookable_window(now, cfg)
            busy = await self._busy([window, wide] if relative_day else [window])
            found = free_slots(*window, part_of_day, cfg.max_slots_returned, busy, cfg)
            if not found and relative_day:
                # Asked-for day is full: widen to the whole horizon, not a dead end.
                wider = free_slots(
                    *wide, part_of_day, cfg.max_slots_returned, busy, cfg
                )
                if wider:
                    return AvailabilityResult(
                        slots=_slots(wider),
                        say=f"Nothing free then, but {join_spoken(wider)}",
                    )
            return AvailabilityResult(slots=_slots(found), say=join_spoken(found))

    async def book(
        self,
        slot_id: str,
        caller_name: str,
        caller_phone: str,
        reason: str | None = None,
    ) -> BookingResult:
        cfg = self.config
        slot = self._parse_slot(slot_id)
        slot_end = slot + timedelta(minutes=cfg.slot_minutes)
        event_id = booking_event_id(self.connection_id, slot, caller_name, caller_phone)
        loop = asyncio.get_running_loop()
        started = loop.time()
        async with self._deadline():
            now = self._now()
            earliest, horizon = wide = bookable_window(now, cfg)
            check: Window = (slot, slot_end + timedelta(minutes=1))
            busy = await self._busy([check, wide])
            still_free = earliest <= slot < horizon and slot in free_slots(
                *check, None, 5, busy, cfg
            )
            if not still_free:
                # A retry of a booking that did go through finds its own event.
                existing = await self.client.get_event(cfg.calendar_id, event_id)
                if existing is not None and self._is_ours(existing):
                    return self._booked(event_id, slot)
                alternatives = free_slots(
                    *wide, None, cfg.max_slots_returned, busy, cfg
                )
                return BookingResult(
                    booked=False,
                    slots=_slots(alternatives),
                    say=f"That one has just gone. {join_spoken(alternatives)}",
                )
        # The insert runs outside the deadline so it is never cancelled half
        # way; it is bounded by its own timeout, from the time that is left.
        remaining = self.deadline_seconds - (loop.time() - started)
        if remaining < self.min_insert_seconds:
            raise GoogleApiError(UNCONFIRMED_BOOKING, retryable=True)
        event = self._event(event_id, slot, slot_end, caller_name, caller_phone, reason)
        timeout = httpx.Timeout(remaining, connect=min(2.0, remaining))
        try:
            created = await self.client.insert_event(
                cfg.calendar_id, event, request_timeout=timeout
            )
            if not created:
                await self._confirm_existing(event)
        except GoogleApiError as exc:
            if exc.retryable:
                raise GoogleApiError(UNCONFIRMED_BOOKING, retryable=True) from None
            raise
        return self._booked(event_id, slot)

    async def _confirm_existing(self, event: dict[str, JsonValue]) -> None:
        """Google already has this id: an earlier attempt, or a cancelled copy."""
        existing = await self.client.get_event(
            self.config.calendar_id, str(event["id"])
        )
        if existing is None:
            raise GoogleApiError(UNCONFIRMED_BOOKING, retryable=True)
        if existing.get("status") == "cancelled":
            await self.client.restore_event(self.config.calendar_id, event)

    def _booked(self, event_id: str, slot: datetime) -> BookingResult:
        return BookingResult(
            booked=True,
            event_id=event_id,
            say=f"That is booked in for {say_time(slot)}.",
        )

    async def cancel(self, event_id: str) -> CancelResult:
        cfg = self.config
        async with self._deadline():
            event = await self.client.get_event(cfg.calendar_id, event_id)
            if event is None or not self._is_ours(event):
                return CancelResult(cancelled=False, say=CANCEL_NOT_FOUND)
            deleted = await self.client.delete_event(cfg.calendar_id, event_id)
        if not deleted:
            return CancelResult(cancelled=False, say=CANCEL_NOT_FOUND)
        when = self._event_start(event)
        say = (
            f"Your appointment for {say_time(when)} is cancelled."
            if when is not None
            else "Your appointment is cancelled."
        )
        return CancelResult(cancelled=True, say=say)

    async def look_up_order(
        self, caller_name: str, address_or_eircode: str, order_id: str | None = None
    ) -> OrderLookupResult:
        sheet_id = self.config.orders_sheet_id
        if not sheet_id:
            raise NotConfiguredError("order lookup is not set up for this connection")
        a1_range = f"{_a1_tab(self.config.orders_tab)}!{SHEET_COLUMNS}"

        async def fetch() -> list[dict[str, str]]:
            return rows_from_values(await self.client.sheet_values(sheet_id, a1_range))

        async with self._deadline():
            rows = await self.orders_cache.rows(
                (self.connection_id, sheet_id, self.config.orders_tab),
                self.clock(),
                fetch,
            )
        return match_order(rows, caller_name, address_or_eircode, order_id)

    async def check_access(self) -> str:
        """Prove the calendar (and orders sheet, if set) can be reached.

        For admins only (connection test): access errors name the Google
        account that needs to be given access.
        """
        try:
            async with self._deadline():
                summary = await self.client.calendar_summary(self.config.calendar_id)
                message = f"Calendar '{summary}' is reachable"
                if self.config.orders_sheet_id:
                    title = await self.client.sheet_title(self.config.orders_sheet_id)
                    message += f"; orders sheet '{title}' is readable"
        except GoogleApiError as exc:
            hint = self.client.account_hint
            if exc.access_problem and hint:
                raise GoogleApiError(
                    f"{exc.access_problem}; make sure it is shared with {hint}",
                    access_problem=exc.access_problem,
                ) from None
            raise
        return message

    def _now(self) -> datetime:
        return self.clock().astimezone(self.config.zone)

    def _parse_slot(self, slot_id: str) -> datetime:
        try:
            slot = datetime.fromisoformat(slot_id.strip())
        except ValueError:
            raise BadArgumentError(BAD_SLOT_ID) from None
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=self.config.zone)
        return slot.astimezone(self.config.zone)

    def _event(
        self,
        event_id: str,
        start: datetime,
        end: datetime,
        caller_name: str,
        caller_phone: str,
        reason: str | None,
    ) -> dict[str, JsonValue]:
        cfg = self.config
        description = "\n".join(
            [
                cfg.booked_by_line,
                f"Caller: {caller_name}",
                f"Phone: {caller_phone}",
                f"Reason: {reason or 'not given'}",
            ]
        )
        return {
            "id": event_id,
            "summary": f"{cfg.event_summary_prefix} — {caller_name}",
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": cfg.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": cfg.timezone},
            "extendedProperties": {
                "private": {BOOKING_MARKER: str(self.connection_id)}
            },
        }

    def _is_ours(self, event: Mapping[str, object]) -> bool:
        if event.get("status") == "cancelled":
            return False
        props = event.get("extendedProperties")
        private = props.get("private") if isinstance(props, dict) else None
        return isinstance(private, dict) and private.get(BOOKING_MARKER) == str(
            self.connection_id
        )

    def _event_start(self, event: dict[str, object]) -> datetime | None:
        start = event.get("start")
        raw = start.get("dateTime") if isinstance(start, dict) else None
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw).astimezone(self.config.zone)
        except ValueError:
            return None

    async def _busy(self, windows: Sequence[Window]) -> list[Busy]:
        """Busy blocks covering ``windows``; one Google call when they are close."""
        usable = [(start, end) for start, end in windows if start < end]
        if not usable:
            return []
        first = min(start for start, _ in usable)
        last = max(end for _, end in usable)
        spans = [(first, last)] if last - first <= MAX_FREEBUSY_SPAN else usable
        busy: list[Busy] = []
        for start, end in spans:
            busy.extend(
                await self.client.free_busy(
                    self.config.calendar_id, start, end, self.config.timezone
                )
            )
        return busy

    @asynccontextmanager
    async def _deadline(self) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(self.deadline_seconds):
                yield
        except TimeoutError:
            raise GoogleApiError("Google did not respond in time") from None


ServiceFactory = Callable[[ConnectionContext], CalendarService]

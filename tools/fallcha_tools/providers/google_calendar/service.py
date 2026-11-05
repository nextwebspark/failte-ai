"""The calendar use cases, shared by the MCP tools and the REST routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import JsonValue

from fallcha_tools.core.provider import ConnectionContext
from fallcha_tools.providers.google_calendar.client import Budget, GoogleClient
from fallcha_tools.providers.google_calendar.credentials import Clock
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    GoogleApiError,
)
from fallcha_tools.providers.google_calendar.matching import (
    CALLER_PREFIX,
    PHONE_KEY_PROPERTY,
    PHONE_PREFIX,
    REASON_PREFIX,
    BookedCaller,
    CallerLookup,
    booked_caller,
    caller_lookup,
    name_matches,
    one_line,
    phone_key,
    phone_matches,
    private_properties,
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
    FindResult,
    FoundAppointment,
    RescheduleOutcome,
    RescheduleResult,
    Slot,
)
from fallcha_tools.providers.google_calendar.settings import (
    MAX_HORIZON_DAYS,
    CalendarConfig,
)
from fallcha_tools.providers.google_calendar.speech import (
    join_spoken,
    say_bookings,
    say_time,
)

# Events this service books carry the connection id here; cancel, find and
# reschedule only touch events whose marker matches the calling connection.
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
MOVE_NOT_FOUND = "I could not find that appointment to move."
DETAILS_EDITED = (
    "The team has changed that appointment, so I cannot move it myself. I can "
    "take a message for them."
)
_NOT_MOVED_SAY = {
    RescheduleOutcome.NOT_FOUND: MOVE_NOT_FOUND,
    RescheduleOutcome.DETAILS_EDITED: DETAILS_EDITED,
}
# A lookup names at most this many upcoming bookings, soonest first.
MAX_FOUND = 3
# A booking never starts more than the longest horizon after it was made, so
# this window holds every upcoming booking, whatever the horizon is now.
LOOKUP_WINDOW = timedelta(days=MAX_HORIZON_DAYS)
# Bookings tagged with the caller's phone key: one page covers any caller.
CALLER_PAGE_SIZE = 25
# Older bookings carry no phone key; their descriptions are read from the
# connection's soonest SCAN_PAGE_SIZE * SCAN_MAX_PAGES upcoming bookings.
SCAN_PAGE_SIZE = 250
SCAN_MAX_PAGES = 2
# Another page of a lookup is only requested with at least this much time left.
DEFAULT_MIN_PAGE_SECONDS = 1.0


# Appended to a booking's id for the one re-insert allowed when Google says
# the id exists (409) but the event cannot be read (deleted for good).
SALTED_SUFFIX = "v1"


def booking_event_id(
    key: bytes,
    connection_id: uuid.UUID,
    slot: datetime,
    caller_name: str,
    caller_phone: str,
) -> str:
    """Deterministic Google event id (base32hex) for one booking request.

    Retrying the same booking re-sends the same id, so Google answers 409
    instead of creating a duplicate. The id is an HMAC under a server key, so
    it reveals nothing about the caller and cannot be predicted from outside.
    """
    phone = "".join(ch for ch in caller_phone if ch.isdigit()) or caller_phone
    seed = "|".join(
        [str(connection_id), slot.isoformat(), caller_name.strip().lower(), phone]
    )
    digest = hmac.new(key, seed.encode(), hashlib.sha256).digest()
    return base64.b32hexencode(digest).decode().rstrip("=").lower()


def _slots(found: Sequence[datetime]) -> list[Slot]:
    return [Slot(id=slot.isoformat(), say=say_time(slot)) for slot in found]


@dataclass(frozen=True, slots=True)
class CalendarService:
    """One connection's calendar, with its booking rules."""

    client: GoogleClient
    config: CalendarConfig
    connection_id: uuid.UUID
    clock: Clock
    booking_id_key: bytes
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    min_insert_seconds: float = DEFAULT_MIN_INSERT_SECONDS
    min_page_seconds: float = DEFAULT_MIN_PAGE_SECONDS
    # The number of the person on the call, from the call record (see
    # ConnectionContext.contact_phone); None when hidden or unknown.
    contact_phone: str | None = None

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
        *,
        notes: Sequence[str] = (),
    ) -> BookingResult:
        """Book ``slot_id``. ``notes`` are extra description lines (the staff
        notes of a booking being moved)."""
        cfg = self.config
        slot = self._parse_slot(slot_id)
        slot_end = slot + timedelta(minutes=cfg.slot_minutes)
        event_id = booking_event_id(
            self.booking_id_key, self.connection_id, slot, caller_name, caller_phone
        )
        candidate_ids = (event_id, event_id + SALTED_SUFFIX)
        budget = Budget(
            deadline_at=asyncio.get_running_loop().time() + self.deadline_seconds,
            min_seconds=self.min_insert_seconds,
        )
        async with self._deadline():
            now = self._now()
            earliest, horizon = wide = bookable_window(now, cfg)
            check: Window = (slot, slot_end + timedelta(minutes=1))
            busy = await self._busy([check, wide])
            alternatives = free_slots(*wide, None, cfg.max_slots_returned, busy, cfg)
            still_free = earliest <= slot < horizon and slot in free_slots(
                *check, None, 5, busy, cfg
            )
            if not still_free:
                # A retry of a booking that did go through finds its own event.
                for candidate in candidate_ids:
                    existing = await self.client.get_event(cfg.calendar_id, candidate)
                    if existing is not None and self._is_ours(existing):
                        return self._booked(candidate, slot)
                return self._gone(alternatives)
        # The insert runs outside the deadline so it is never cancelled half
        # way; each request gets the time that is left as its timeout, and no
        # request starts with less than ``min_insert_seconds`` left.
        try:
            for candidate in candidate_ids:
                event = self._event(
                    candidate,
                    slot,
                    slot_end,
                    BookedCaller(caller_name, caller_phone, reason, tuple(notes)),
                )
                if await self._insert_or_confirm(event, budget):
                    return self._booked(candidate, slot)
        except GoogleApiError as exc:
            if exc.retryable:
                raise GoogleApiError(UNCONFIRMED_BOOKING, retryable=True) from None
            raise
        # Both ids exist on Google but neither can be read: give up cleanly.
        return self._gone(alternatives)

    async def _insert_or_confirm(
        self, event: dict[str, JsonValue], budget: Budget
    ) -> bool:
        """True if ``event`` is (now) booked; False if its id is unusable.

        Google answers 409 when the id exists: an earlier attempt (booked), a
        cancelled copy (restored), or a deleted-for-good event that can no
        longer be read (False: the caller tries the next id).
        """
        calendar_id = self.config.calendar_id
        self._require_time(budget)
        if await self.client.insert_event(calendar_id, event, budget=budget):
            return True
        self._require_time(budget)
        existing = await self.client.get_event(
            calendar_id, str(event["id"]), budget=budget
        )
        if existing is None or not self._is_ours(existing, include_cancelled=True):
            return False
        if existing.get("status") == "cancelled":
            self._require_time(budget)
            await self.client.restore_event(calendar_id, event, budget=budget)
        return True

    @staticmethod
    def _require_time(budget: Budget) -> None:
        if not budget.allows_request():
            raise GoogleApiError(UNCONFIRMED_BOOKING, retryable=True)

    def _gone(self, alternatives: Sequence[datetime]) -> BookingResult:
        return BookingResult(
            booked=False,
            slots=_slots(alternatives),
            say=f"That one has just gone. {join_spoken(alternatives)}",
        )

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

    async def reschedule(self, event_id: str, slot_id: str) -> RescheduleResult:
        """Move a booking to ``slot_id``: book the new time for the same
        caller first, then cancel the old booking, so a failure never leaves
        the caller without an appointment."""
        slot = self._parse_slot(slot_id)
        async with self._deadline():
            old = await self.client.get_event(self.config.calendar_id, event_id)
            if old is not None and old.get("status") == "cancelled":
                return await self._finished_move(old, slot)
        movable = self._movable(old)
        if not isinstance(movable, tuple):
            return RescheduleResult(outcome=movable, say=_NOT_MOVED_SAY[movable])
        start, caller = movable
        if slot == start:
            # Booking it again would find the old event and cancel it.
            return RescheduleResult(
                outcome=RescheduleOutcome.UNCHANGED,
                say=f"You are already booked in for {say_time(start)}.",
            )
        booking = await self.book(
            slot_id, caller.name, caller.phone, caller.reason, notes=caller.notes
        )
        if not booking.booked or booking.event_id is None:
            return RescheduleResult(
                outcome=RescheduleOutcome.SLOT_TAKEN,
                slots=booking.slots,
                say=f"{booking.say} Your appointment for {say_time(start)} "
                "is still booked.",
            )
        return await self._cancel_moved(event_id, start, booking.event_id, slot)

    def _movable(
        self, event: Mapping[str, object] | None
    ) -> tuple[datetime, BookedCaller] | RescheduleOutcome:
        """Start and caller of ``event`` if it is an upcoming booking of ours
        whose caller details are intact, else why it cannot be moved."""
        start = self._event_start(event) if event is not None else None
        if (
            event is None
            or start is None
            or start <= self._now()
            or not self._is_ours(event)
        ):
            return RescheduleOutcome.NOT_FOUND
        caller = booked_caller(event)
        if caller is None:
            return RescheduleOutcome.DETAILS_EDITED
        return start, caller

    async def _finished_move(
        self, old: Mapping[str, object], slot: datetime
    ) -> RescheduleResult:
        """A retry of a move whose reply was lost: ``old`` (ours, cancelled)
        was moved if the booking ``reschedule`` makes for ``slot`` exists."""
        start = self._event_start(old)
        caller = booked_caller(old)
        if (
            not self._is_ours(old, include_cancelled=True)
            or start is None
            or not caller
        ):
            return RescheduleResult(
                outcome=RescheduleOutcome.NOT_FOUND, say=MOVE_NOT_FOUND
            )
        new_id = booking_event_id(
            self.booking_id_key, self.connection_id, slot, caller.name, caller.phone
        )
        for candidate in (new_id, new_id + SALTED_SUFFIX):
            new = await self.client.get_event(self.config.calendar_id, candidate)
            if (
                new is not None
                and self._is_ours(new)
                and self._event_start(new) == slot
            ):
                return self._moved(candidate, start, slot)
        return RescheduleResult(outcome=RescheduleOutcome.NOT_FOUND, say=MOVE_NOT_FOUND)

    async def _cancel_moved(
        self, old_id: str, old_start: datetime, new_id: str, new_start: datetime
    ) -> RescheduleResult:
        """Cancel the booking that ``new_id`` replaces (gone already is fine)."""
        try:
            async with self._deadline():
                await self.client.delete_event(self.config.calendar_id, old_id)
        except GoogleApiError as exc:
            logger.warning(
                "calendar reschedule for connection {} kept the old booking: {}",
                self.connection_id,
                exc,
            )
            return RescheduleResult(
                outcome=RescheduleOutcome.OLD_NOT_CANCELLED,
                event_id=new_id,
                say=(
                    f"You are booked in for {say_time(new_start)}, but I could "
                    f"not cancel your appointment for {say_time(old_start)}, so "
                    "the team will need to remove it."
                ),
            )
        return self._moved(new_id, old_start, new_start)

    @staticmethod
    def _moved(
        new_id: str, old_start: datetime, new_start: datetime
    ) -> RescheduleResult:
        return RescheduleResult(
            outcome=RescheduleOutcome.MOVED,
            event_id=new_id,
            say=(
                f"Your appointment is moved from {say_time(old_start)} to "
                f"{say_time(new_start)}."
            ),
        )

    async def find(
        self, caller_phone: str | None = None, caller_name: str | None = None
    ) -> FindResult:
        """The caller's upcoming bookings by this connection, soonest first.

        Bookings are matched by phone number (see ``matching.caller_lookup``
        for which number a caller may use); ``caller_name`` never widens them.
        """
        lookup = caller_lookup(
            contact_phone=self.contact_phone,
            caller_phone=caller_phone,
            caller_name=caller_name,
        )
        key = lookup.phone_key
        budget = Budget.starting_now(
            self.deadline_seconds, min_seconds=self.min_page_seconds
        )
        async with self._deadline():
            now = self._now()
            ours = {BOOKING_MARKER: str(self.connection_id)}
            tagged, scanned = await asyncio.gather(
                self._upcoming_events(
                    {**ours, PHONE_KEY_PROPERTY: key}, now, budget, CALLER_PAGE_SIZE
                ),
                # Bookings made before they carried the phone key. Once all of
                # those are past (MAX_HORIZON_DAYS after that release), this
                # only finds tagged bookings again and can be dropped.
                # TODO(2027-02-01): drop this scan (and SCAN_*) if the release
                # carrying the phone key shipped before 2026-12-01.
                self._upcoming_events(
                    ours, now, budget, SCAN_PAGE_SIZE, max_pages=SCAN_MAX_PAGES
                ),
            )
        found = self._callers([*tagged, *scanned], lookup=lookup, now=now)
        return FindResult(
            appointments=[
                FoundAppointment(
                    event_id=event_id, start=start.isoformat(), say=say_time(start)
                )
                for event_id, start in found
            ],
            say=say_bookings([start for _, start in found]),
        )

    async def _upcoming_events(
        self,
        properties: Mapping[str, str],
        now: datetime,
        budget: Budget,
        page_size: int,
        *,
        max_pages: int = 1,
    ) -> list[dict[str, Any]]:
        return await self.client.list_events(
            self.config.calendar_id,
            private_properties=properties,
            time_min=now,
            time_max=now + LOOKUP_WINDOW,
            page_size=page_size,
            max_pages=max_pages,
            budget=budget,
        )

    def _callers(
        self,
        events: Iterable[Mapping[str, object]],
        *,
        lookup: CallerLookup,
        now: datetime,
    ) -> list[tuple[str, datetime]]:
        """(event id, start) of the caller's bookings among ``events``.

        Every event is checked here, whatever Google filtered on: a booking
        is returned only if it is ours, not started and matches ``lookup``.
        """
        found: dict[str, datetime] = {}
        for event in events:
            event_id = event.get("id")
            start = self._event_start(event)
            if (
                isinstance(event_id, str)
                and start is not None
                and start > now
                and self._is_ours(event)
                and phone_matches(event, lookup, self.config.default_phone_region)
                and name_matches(lookup.name, event)
            ):
                found[event_id] = start
        return sorted(found.items(), key=lambda item: item[1])[:MAX_FOUND]

    async def check_access(self) -> str:
        """Prove the calendar can be reached.

        For admins only (connection test): access errors name the Google
        account that needs to be given access.
        """
        try:
            async with self._deadline():
                summary = await self.client.calendar_summary(self.config.calendar_id)
                message = f"Calendar '{summary}' is reachable"
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
        caller: BookedCaller,
    ) -> dict[str, JsonValue]:
        cfg = self.config
        caller_name, caller_phone = one_line(caller.name), one_line(caller.phone)
        description = "\n".join(
            [
                cfg.booked_by_line,
                f"{CALLER_PREFIX}{caller_name}",
                f"{PHONE_PREFIX}{caller_phone}",
                f"{REASON_PREFIX}{one_line(caller.reason or '') or 'not given'}",
                *(one_line(note) for note in caller.notes),
            ]
        )
        private: dict[str, JsonValue] = {BOOKING_MARKER: str(self.connection_id)}
        key = phone_key(caller_phone)
        if key is not None:
            # Lets find_appointments ask Google for the caller's bookings only.
            private[PHONE_KEY_PROPERTY] = key
        return {
            "id": event_id,
            "summary": f"{cfg.event_summary_prefix} — {caller_name}",
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": cfg.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": cfg.timezone},
            "extendedProperties": {"private": private},
        }

    def _is_ours(
        self, event: Mapping[str, object], *, include_cancelled: bool = False
    ) -> bool:
        if event.get("status") == "cancelled" and not include_cancelled:
            return False
        marker = private_properties(event).get(BOOKING_MARKER)
        return marker == str(self.connection_id)

    def _event_start(self, event: Mapping[str, object]) -> datetime | None:
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

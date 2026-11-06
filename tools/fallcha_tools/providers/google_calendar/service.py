"""The calendar use cases, shared by the MCP tools and the REST routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
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
    PARTY_PREFIX,
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
    Booked,
    Busy,
    Window,
    bookable_window,
    candidate_slots,
    free_slots,
    has_room,
    open_slots,
    resolve_window,
)
from fallcha_tools.providers.google_calendar.schemas import (
    AvailabilityResult,
    Booking,
    BookingResult,
    CancelResult,
    FindResult,
    FoundAppointment,
    Handoff,
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
# Party size of an agent booking, so capacity is counted without parsing.
PARTY_SIZE_PROP = "fallcha_party_size"
# Busy lookups for windows closer together than this share one freeBusy call.
MAX_FREEBUSY_SPAN = timedelta(days=60)
# Longest range the bookings list reads in one request.
MAX_LIST_SPAN = timedelta(days=62)
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
NEED_PARTY_SIZE = "party_size is required: ask how many people the booking is for"

SAY_BOOKING_OFF = (
    "I can't book that on this call, but I can take your details and the team "
    "will get back to you to confirm."
)
SAY_ASK_PARTY = "How many people is the booking for?"
SAY_CHANGES_OFF = (
    "I can't change bookings on this call, but I can take your details and "
    "the team will sort it out for you."
)
# With changes off, only a booking made on this call may still be cancelled.
# The tools service keeps no call state, so "this call" is any booking Google
# created no longer ago than the longest call (20 minutes) plus slack. Event
# ids are unguessable HMACs, so an agent only knows the id of a booking it
# made on this call or found with find_appointments (which is off too).
SAME_CALL_WINDOW = timedelta(minutes=30)
# Words that make a calendar event someone else added count as a booking of
# that many people rather than closing the time: "Table for 4 - Byrne",
# "Party of 6", "Murphy 3 pax", "8 guests". Any other Busy event (a staff
# meeting, "Private party", "Closed") closes its time.
_PARTY_IN_TITLE = re.compile(
    r"(?:table|booking|reservation)\s+for\s+(\d{1,3})\b"
    r"|party\s+of\s+(\d{1,3})\b"
    r"|\b(\d{1,3})\s*(?:people|persons|guests|pax|covers|ppl)\b",
    re.IGNORECASE,
)
_CLOSED_WORD = re.compile(r"\bclosed\b", re.IGNORECASE)
# One capacity booking at a time per connection in this process; across
# processes the check after insert (``_kept_after_race``) decides.
_BOOKING_LOCKS: dict[uuid.UUID, asyncio.Lock] = {}
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


SlotFinder = Callable[[Window, str | None], list[datetime]]


@dataclass(frozen=True, slots=True)
class CalendarService:
    """One connection's calendar, with its booking rules.

    Two ways of counting, chosen by the config:

    - a diary (``max_bookings_at_once`` 1, no guest limits): Google's
      free/busy decides, so any busy event blocks the time;
    - capacity (tables, chairs, rooms): the calendar's events are read and
      counted, see ``_classify`` and ``scheduling.has_room``.
    """

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
        self,
        relative_day: str | None,
        part_of_day: str | None,
        party_size: int | None = None,
    ) -> AvailabilityResult:
        cfg = self.config
        refusal = self._refusal(party_size)
        if refusal is not None:
            return AvailabilityResult(slots=[], say=refusal[1], handoff=refusal[0])
        if cfg.needs_party_size and party_size is None:
            return AvailabilityResult(
                slots=[], say=SAY_ASK_PARTY, needs_party_size=True
            )
        async with self._deadline():
            now = self._now()
            window = resolve_window(relative_day, now, cfg)
            wide = bookable_window(now, cfg)
            find = await self._slot_finder(
                [window, wide] if relative_day else [window], party_size
            )
            found = find(window, part_of_day)
            if not found and relative_day:
                # Asked-for day is full: widen to the whole horizon, not a dead end.
                wider = find(wide, part_of_day)
                if wider:
                    return AvailabilityResult(
                        slots=_slots(wider),
                        say=f"Nothing free then, but {join_spoken(wider)}",
                    )
            if not found and cfg.counts_capacity and not find(wide, None):
                return self._fully_booked()
            return AvailabilityResult(slots=_slots(found), say=join_spoken(found))

    async def book(
        self,
        slot_id: str,
        caller_name: str,
        caller_phone: str,
        reason: str | None = None,
        party_size: int | None = None,
        *,
        notes: Sequence[str] = (),
        replacing: str | None = None,
    ) -> BookingResult:
        """Book ``slot_id``. ``notes`` are extra description lines (the staff
        notes of a booking being moved); ``replacing`` is the event id of that
        booking, which does not count against capacity for the new time."""
        cfg = self.config
        refusal = self._refusal(party_size)
        if refusal is not None:
            return BookingResult(booked=False, say=refusal[1], handoff=refusal[0])
        if cfg.needs_party_size and party_size is None:
            raise BadArgumentError(NEED_PARTY_SIZE)
        slot = self._parse_slot(slot_id)
        caller = BookedCaller(caller_name, caller_phone, reason, tuple(notes))
        if not cfg.counts_capacity:
            return await self._book_slot(slot, caller, party_size, replacing)
        lock = _BOOKING_LOCKS.setdefault(self.connection_id, asyncio.Lock())
        async with lock:
            return await self._book_slot(slot, caller, party_size, replacing)

    async def _book_slot(
        self,
        slot: datetime,
        caller: BookedCaller,
        party_size: int | None,
        replacing: str | None,
    ) -> BookingResult:
        cfg = self.config
        caller_name, caller_phone = caller.name, caller.phone
        slot_end = slot + timedelta(minutes=cfg.booking_length)
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
            alternatives, open_now = await self._check_slot(
                slot, check, wide, party_size, replacing
            )
            if not (open_now and earliest <= slot < horizon):
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
                    caller,
                    party_size,
                )
                if await self._insert_or_confirm(event, budget):
                    if cfg.counts_capacity and not await self._kept_after_race(
                        candidate, slot, party_size, budget, replacing
                    ):
                        # The alternatives predate the race: drop the lost time.
                        return self._gone([a for a in alternatives if a != slot])
                    return self._booked(candidate, slot)
        except GoogleApiError as exc:
            if exc.retryable:
                raise GoogleApiError(UNCONFIRMED_BOOKING, retryable=True) from None
            raise
        # Both ids exist on Google but neither can be read: give up cleanly.
        return self._gone(alternatives)

    def _refusal(self, party_size: int | None) -> tuple[Handoff, str] | None:
        """Why this request must go to a person, before any calendar call."""
        cfg = self.config
        if not cfg.ai_booking_enabled:
            return "booking_off", SAY_BOOKING_OFF
        if party_size is None:
            return None
        if cfg.max_party_size is not None and party_size > cfg.max_party_size:
            return (
                "party_too_large",
                f"For a group of {party_size}, the team arranges that directly. "
                "I can take your details and they will call you back.",
            )
        if party_size < cfg.min_party_size:
            return (
                "party_too_small",
                f"We take bookings for {cfg.min_party_size} or more. I can take "
                "your details and the team will get back to you.",
            )
        return None

    def _fully_booked(self) -> AvailabilityResult:
        days = self.config.horizon_days
        return AvailabilityResult(
            slots=[],
            say=(
                f"I'm sorry, we're fully booked for the next {days} days. I can "
                "take your details and the team will call if a place opens up."
            ),
            handoff="fully_booked",
        )

    async def _slot_finder(
        self, windows: Sequence[Window], party_size: int | None
    ) -> SlotFinder:
        """Read the calendar once for ``windows``; the returned function
        finds free slots in any of them."""
        cfg = self.config
        limit = cfg.max_slots_returned
        if not cfg.counts_capacity:
            busy = await self._busy(windows)
            return lambda w, part: free_slots(*w, part, limit, busy, cfg)
        booked, blocked = await self._occupancy(windows)
        return lambda w, part: open_slots(
            *w, part, limit, booked, blocked, cfg, party_size
        )

    async def _check_slot(
        self,
        slot: datetime,
        check: Window,
        wide: Window,
        party_size: int | None,
        replacing: str | None = None,
    ) -> tuple[list[datetime], bool]:
        """(alternatives, whether ``slot`` is still an open start time).
        ``replacing`` (a booking being moved) is left out of the count."""
        cfg = self.config
        limit = cfg.max_slots_returned
        if not cfg.counts_capacity:
            busy = await self._busy([check, wide])
            alternatives = free_slots(*wide, None, limit, busy, cfg)
            return alternatives, slot in free_slots(*check, None, 5, busy, cfg)
        booked, blocked = await self._occupancy([check, wide], ignore=replacing)
        alternatives = open_slots(*wide, None, limit, booked, blocked, cfg, party_size)
        allowed = slot in candidate_slots(*check, None, cfg)
        return alternatives, allowed and has_room(
            slot, booked, blocked, cfg, party_size
        )

    async def _kept_after_race(
        self,
        event_id: str,
        slot: datetime,
        party_size: int | None,
        budget: Budget,
        replacing: str | None = None,
    ) -> bool:
        """Re-read the calendar after inserting a capacity booking.

        If bookings made earlier (by Google's ``created`` time, then id)
        already fill the time, another call took the last place: delete ours
        and report the slot gone. Every racing call sorts the same way, so
        exactly the earlier bookings stay.
        """
        cfg = self.config
        reach = timedelta(minutes=cfg.booking_length + cfg.buffer_minutes)
        try:
            if not budget.allows_request():
                raise GoogleApiError("no time left to re-check", retryable=True)
            events = await self.client.list_events(
                cfg.calendar_id, slot - reach, slot + reach, budget=budget
            )
        except GoogleApiError:
            # Booked but unchecked: keep it rather than drop a real booking.
            logger.warning(
                "booking {} on connection {} kept without the race check",
                event_id,
                self.connection_id,
            )
            return True
        mine = next((e for e in events if e.get("id") == event_id), None)
        if mine is None:
            return True
        order = (str(mine.get("created") or ""), event_id)
        booked: list[Booked] = []
        blocked: list[Busy] = []
        for event in events:
            other = (str(event.get("created") or ""), str(event.get("id") or ""))
            if other >= order or (replacing and event.get("id") == replacing):
                continue
            self._classify(event, booked, blocked)
        if has_room(slot, booked, blocked, cfg, party_size):
            return True
        logger.info(
            "booking {} lost the last place at {} on connection {}; removing it",
            event_id,
            slot.isoformat(),
            self.connection_id,
        )
        await self.client.delete_event(cfg.calendar_id, event_id)
        return False

    async def list_bookings(self, start: datetime, end: datetime) -> list[Booking]:
        """Bookings this connection made that overlap [start, end), in start
        order, including ones cancelled since."""
        if end <= start:
            raise BadArgumentError("end must be after start")
        if end - start > MAX_LIST_SPAN:
            raise BadArgumentError("ask for at most 62 days of bookings at a time")
        async with self._deadline():
            events = await self.client.list_events(
                self.config.calendar_id,
                start,
                end,
                show_deleted=True,
                private_property=f"{BOOKING_MARKER}={self.connection_id}",
            )
        bookings = [self._booking(event) for event in events]
        return [b for b in bookings if b is not None]

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
        if not alternatives and self.config.counts_capacity:
            full = self._fully_booked()
            return BookingResult(
                booked=False, slots=[], say=full.say, handoff=full.handoff
            )
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
            starts_at=slot.isoformat(),
        )

    async def cancel(self, event_id: str) -> CancelResult:
        """Cancel a booking this connection made. With ``ai_changes_enabled``
        off, only a booking made on this call (see ``SAME_CALL_WINDOW``) may
        be cancelled; an older one is handed off untouched."""
        cfg = self.config
        async with self._deadline():
            event = await self.client.get_event(cfg.calendar_id, event_id)
            if event is None or not self._is_ours(event):
                return CancelResult(cancelled=False, say=CANCEL_NOT_FOUND)
            if not cfg.ai_changes_enabled and not self._made_this_call(event):
                return CancelResult(
                    cancelled=False, say=SAY_CHANGES_OFF, handoff="changes_off"
                )
            deleted = await self.client.delete_event(cfg.calendar_id, event_id)
        if not deleted:
            return CancelResult(cancelled=False, say=CANCEL_NOT_FOUND)
        when = self._event_start(event)
        say = (
            f"Your appointment for {say_time(when)} is cancelled."
            if when is not None
            else "Your appointment is cancelled."
        )
        return CancelResult(
            cancelled=True,
            say=say,
            starts_at=when.isoformat() if when is not None else None,
        )

    def _made_this_call(self, event: Mapping[str, object]) -> bool:
        """Whether Google created ``event`` recently enough to be this call's
        own booking; an unreadable ``created`` counts as an older booking."""
        raw = event.get("created")
        if not isinstance(raw, str):
            return False
        try:
            created = datetime.fromisoformat(raw)
        except ValueError:
            return False
        if created.tzinfo is None:
            return False
        return self._now() - created <= SAME_CALL_WINDOW

    async def reschedule(self, event_id: str, slot_id: str) -> RescheduleResult:
        """Move a booking to ``slot_id``: book the new time for the same
        caller first, then cancel the old booking, so a failure never leaves
        the caller without an appointment. Off unless the owner allows
        changes (``ai_changes_enabled``); the calendar is not touched then."""
        if not self.config.ai_changes_enabled:
            return RescheduleResult(
                outcome=RescheduleOutcome.HANDED_OFF,
                say=SAY_CHANGES_OFF,
                handoff="changes_off",
            )
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
            slot_id,
            caller.name,
            caller.phone,
            caller.reason,
            self._party_of(old) if old is not None else None,
            notes=caller.notes,
            replacing=event_id,
        )
        if booking.handoff is not None and not booking.booked:
            return RescheduleResult(
                outcome=RescheduleOutcome.HANDED_OFF,
                handoff=booking.handoff,
                say=f"{booking.say} Your appointment for {say_time(start)} "
                "is still booked.",
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
                starts_at=new_start.isoformat(),
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
            starts_at=new_start.isoformat(),
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
        Off unless the owner allows changes (``ai_changes_enabled``): then
        nothing is read and the caller is handed off.
        """
        if not self.config.ai_changes_enabled:
            return FindResult(
                appointments=[], say=SAY_CHANGES_OFF, handoff="changes_off"
            )
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
        return await self.client.list_tagged_events(
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
        party_size: int | None = None,
    ) -> dict[str, JsonValue]:
        cfg = self.config
        caller_name, caller_phone = one_line(caller.name), one_line(caller.phone)
        lines = [
            cfg.booked_by_line,
            f"{CALLER_PREFIX}{caller_name}",
            f"{PHONE_PREFIX}{caller_phone}",
        ]
        if party_size is not None:
            lines.append(f"{PARTY_PREFIX}{party_size}")
        lines.append(f"{REASON_PREFIX}{one_line(caller.reason or '') or 'not given'}")
        lines.extend(one_line(note) for note in caller.notes)
        private: dict[str, JsonValue] = {BOOKING_MARKER: str(self.connection_id)}
        key = phone_key(caller_phone)
        if key is not None:
            # Lets find_appointments ask Google for the caller's bookings only.
            private[PHONE_KEY_PROPERTY] = key
        if party_size is not None:
            private[PARTY_SIZE_PROP] = str(party_size)
            title = cfg.party_summary.replace("{n}", str(party_size))
        else:
            title = cfg.event_summary_prefix
        return {
            "id": event_id,
            "summary": f"{title} — {caller_name}",
            "description": "\n".join(lines),
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

    async def _occupancy(
        self, windows: Sequence[Window], *, ignore: str | None = None
    ) -> tuple[list[Booked], list[Busy]]:
        """Bookings and blocking events around ``windows``, from one read.

        Starts early enough to see bookings that began before a window but
        are still running in it.
        """
        usable = [(start, end) for start, end in windows if start < end]
        if not usable:
            return [], []
        cfg = self.config
        reach = timedelta(minutes=cfg.booking_length + cfg.buffer_minutes)
        first = min(start for start, _ in usable) - reach
        last = max(end for _, end in usable) + reach
        events = await self.client.list_events(cfg.calendar_id, first, last)
        booked: list[Booked] = []
        blocked: list[Busy] = []
        for event in events:
            if ignore is None or event.get("id") != ignore:
                self._classify(event, booked, blocked)
        return booked, blocked

    def _classify(
        self, event: Mapping[str, Any], booked: list[Booked], blocked: list[Busy]
    ) -> None:
        """Sort one calendar event into a booking, a block, or nothing.

        - cancelled events, and events shown as Free, are ignored; except an
          all-day event whose title says "closed", which closes the day
          (Google shows all-day events as Free unless told otherwise);
        - this connection's bookings count with their stored party size;
        - another timed event whose title names a party size ("Table for 4")
          counts as a booking of that many people;
        - any other Busy event closes its time.
        """
        if event.get("status") == "cancelled":
            return
        span = self._event_span(event)
        if span is None:
            return
        title = str(event.get("summary") or "")
        start = event.get("start")
        all_day = isinstance(start, dict) and "date" in start
        if event.get("transparency") == "transparent":
            if all_day and _CLOSED_WORD.search(title):
                blocked.append(span)
            return
        if self._is_ours(event):
            booked.append(Booked(*span, guests=self._party_of(event) or 1))
            return
        match = _PARTY_IN_TITLE.search(title)
        if match and not all_day:
            guests = int(next(g for g in match.groups() if g))
            booked.append(Booked(*span, guests=max(guests, 1)))
            return
        blocked.append(span)

    def _event_span(self, event: Mapping[str, Any]) -> Busy | None:
        zone = self.config.zone
        start, end = event.get("start"), event.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            return None
        try:
            if "dateTime" in start and "dateTime" in end:
                return (
                    datetime.fromisoformat(start["dateTime"]).astimezone(zone),
                    datetime.fromisoformat(end["dateTime"]).astimezone(zone),
                )
            if "date" in start and "date" in end:
                return (
                    datetime.fromisoformat(start["date"]).replace(tzinfo=zone),
                    datetime.fromisoformat(end["date"]).replace(tzinfo=zone),
                )
        except (TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _party_of(event: Mapping[str, Any]) -> int | None:
        props = event.get("extendedProperties")
        private = props.get("private") if isinstance(props, dict) else None
        raw = private.get(PARTY_SIZE_PROP) if isinstance(private, dict) else None
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _booking(self, event: Mapping[str, Any]) -> Booking | None:
        span = self._event_span(event)
        event_id = event.get("id")
        if span is None or not isinstance(event_id, str):
            return None
        fields: dict[str, str] = {}
        for line in str(event.get("description") or "").splitlines():
            key, sep, value = line.partition(":")
            if sep:
                fields.setdefault(key.strip().lower(), value.strip())
        reason = fields.get("reason")
        created = event.get("created")
        try:
            created_at = (
                datetime.fromisoformat(created) if isinstance(created, str) else None
            )
        except ValueError:
            created_at = None
        return Booking(
            event_id=event_id,
            start=span[0],
            end=span[1],
            status="cancelled" if event.get("status") == "cancelled" else "confirmed",
            caller_name=fields.get("caller") or None,
            caller_phone=fields.get("phone") or None,
            party_size=self._party_of(event),
            reason=None if reason in (None, "", "not given") else reason,
            created_at=created_at,
        )

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

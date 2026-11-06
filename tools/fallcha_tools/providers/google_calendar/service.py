"""The calendar use cases, shared by the MCP tools and the REST routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
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
    FindBookingResult,
    FoundBooking,
    Handoff,
    Slot,
)
from fallcha_tools.providers.google_calendar.settings import CalendarConfig
from fallcha_tools.providers.google_calendar.speech import join_spoken, say_time

# Events this service books carry the connection id here; cancel only
# touches events whose marker matches the calling connection.
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
SAY_NOT_FOUND = (
    "I couldn't find a booking under those details. I can take a message so "
    "the team can sort it out."
)
NEED_NAME_OR_DAY = (
    "ask for the name the booking is under or the day of the booking, then "
    "call find_booking again"
)
MAX_FOUND_BOOKINGS = 3


def _digits(value: str | None) -> str:
    return "".join(ch for ch in value or "" if ch.isdigit())


def _same_phone(given: str, stored: str | None) -> bool:
    """Same number written differently ("087 123 4567", "+353871234567"):
    compare the last 9 digits; too short to tell never matches."""
    a, b = _digits(given), _digits(stored)
    if len(a) < 7 or len(b) < 7:
        return False
    return a[-9:] == b[-9:]


def _same_name(given: str, stored: str | None) -> bool:
    """Any shared word of 2+ letters, ignoring case: "Byrne" matches
    "Mary Byrne"."""
    words = {w for w in re.findall(r"[a-z']+", given.lower()) if len(w) >= 2}
    stored_words = set(re.findall(r"[a-z']+", (stored or "").lower()))
    return bool(words & stored_words)


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
    ) -> BookingResult:
        cfg = self.config
        refusal = self._refusal(party_size)
        if refusal is not None:
            return BookingResult(booked=False, say=refusal[1], handoff=refusal[0])
        if cfg.needs_party_size and party_size is None:
            raise BadArgumentError(NEED_PARTY_SIZE)
        slot = self._parse_slot(slot_id)
        if not cfg.counts_capacity:
            return await self._book_slot(
                slot, caller_name, caller_phone, reason, party_size
            )
        lock = _BOOKING_LOCKS.setdefault(self.connection_id, asyncio.Lock())
        async with lock:
            return await self._book_slot(
                slot, caller_name, caller_phone, reason, party_size
            )

    async def _book_slot(
        self,
        slot: datetime,
        caller_name: str,
        caller_phone: str,
        reason: str | None,
        party_size: int | None,
    ) -> BookingResult:
        cfg = self.config
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
                slot, check, wide, party_size
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
                    caller_name,
                    caller_phone,
                    reason,
                    party_size,
                )
                if await self._insert_or_confirm(event, budget):
                    if cfg.counts_capacity and not await self._kept_after_race(
                        candidate, slot, party_size, budget
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
    ) -> tuple[list[datetime], bool]:
        """(alternatives, whether ``slot`` is still an open start time)."""
        cfg = self.config
        limit = cfg.max_slots_returned
        if not cfg.counts_capacity:
            busy = await self._busy([check, wide])
            alternatives = free_slots(*wide, None, limit, busy, cfg)
            return alternatives, slot in free_slots(*check, None, 5, busy, cfg)
        booked, blocked = await self._occupancy([check, wide])
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
            if other >= order:
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
        )

    async def find_booking(
        self, caller_phone: str, caller_name: str | None, booking_day: str | None
    ) -> FindBookingResult:
        """Upcoming bookings this connection made that match the caller.

        Verification: the phone number the booking was made under must match
        (last 9 digits, so "087…" and "+353 87…" agree), and so must either
        the name (any shared word, so a surname alone is enough) or the day.
        Off unless the owner allowed changes; nothing found hands off.
        """
        cfg = self.config
        if not cfg.ai_changes_enabled:
            return FindBookingResult(
                bookings=[], say=SAY_CHANGES_OFF, handoff="changes_off"
            )
        name = (caller_name or "").strip()
        day = (booking_day or "").strip()
        if not name and not day:
            raise BadArgumentError(NEED_NAME_OR_DAY)
        async with self._deadline():
            now = self._now()
            end = now + timedelta(days=cfg.horizon_days)
            events = await self.client.list_events(
                cfg.calendar_id,
                now,
                end,
                private_property=f"{BOOKING_MARKER}={self.connection_id}",
            )
        day_window = (
            resolve_window(day, now, cfg.model_copy(update={"min_lead_hours": 0}))
            if day
            else None
        )
        matches: list[Booking] = []
        for event in events:
            booking = self._booking(event)
            if booking is None or booking.status != "confirmed":
                continue
            if booking.start < now or not _same_phone(
                caller_phone, booking.caller_phone
            ):
                continue
            name_ok = bool(name) and _same_name(name, booking.caller_name)
            day_ok = day_window is not None and (
                day_window[0] <= booking.start < day_window[1]
            )
            if name_ok or day_ok:
                matches.append(booking)
        matches = matches[:MAX_FOUND_BOOKINGS]
        if not matches:
            return FindBookingResult(
                bookings=[], say=SAY_NOT_FOUND, handoff="booking_not_found"
            )
        found = [
            FoundBooking(event_id=b.event_id, say=self._describe(b)) for b in matches
        ]
        if len(found) == 1:
            say = f"I have your booking for {found[0].say}. Is that the one?"
        else:
            listed = ", ".join(f.say for f in found[:-1])
            say = f"I have bookings for {listed}, and {found[-1].say}. Which one?"
        return FindBookingResult(bookings=found, say=say)

    async def move(self, event_id: str, slot_id: str) -> BookingResult:
        """Move a booking: book the new time with the same details first, and
        only then remove the old one, so a failure never leaves the caller
        with no booking."""
        cfg = self.config
        if not cfg.ai_changes_enabled:
            return BookingResult(
                booked=False, say=SAY_CHANGES_OFF, handoff="changes_off"
            )
        async with self._deadline():
            event = await self.client.get_event(cfg.calendar_id, event_id)
        old = self._booking(event) if event and self._is_ours(event) else None
        if old is None or old.status != "confirmed":
            return BookingResult(
                booked=False, say=SAY_NOT_FOUND, handoff="booking_not_found"
            )
        if self._parse_slot(slot_id) == old.start:
            return BookingResult(
                booked=False,
                say=f"That is the time you already have, {say_time(old.start)}.",
            )
        result = await self.book(
            slot_id,
            old.caller_name or "Caller",
            old.caller_phone or "",
            old.reason,
            old.party_size,
        )
        if not result.booked or not result.event_id:
            return result
        new_start = self._parse_slot(slot_id)
        try:
            await self.client.delete_event(cfg.calendar_id, event_id)
        except GoogleApiError:
            logger.warning(
                "moved booking {} to {} on connection {}; the old one was not removed",
                event_id,
                result.event_id,
                self.connection_id,
            )
            return BookingResult(
                booked=True,
                event_id=result.event_id,
                say=(
                    f"Your new time is booked for {say_time(new_start)}. The team "
                    "will remove the old booking."
                ),
            )
        return BookingResult(
            booked=True,
            event_id=result.event_id,
            say=f"Done. Your booking is moved to {say_time(new_start)}.",
        )

    def _describe(self, booking: Booking) -> str:
        party = f", for {booking.party_size}" if booking.party_size is not None else ""
        return f"{say_time(booking.start)}{party}"

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
        caller_name: str,
        caller_phone: str,
        reason: str | None,
        party_size: int | None = None,
    ) -> dict[str, JsonValue]:
        cfg = self.config
        lines = [cfg.booked_by_line, f"Caller: {caller_name}", f"Phone: {caller_phone}"]
        if party_size is not None:
            lines.append(f"Party size: {party_size}")
        lines.append(f"Reason: {reason or 'not given'}")
        private: dict[str, JsonValue] = {BOOKING_MARKER: str(self.connection_id)}
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

    async def _occupancy(
        self, windows: Sequence[Window]
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

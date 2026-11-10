"""The Calendly use cases behind the MCP tools.

Free times come from ``GET /event_type_available_times`` for the event type
the owner picked; Calendly's own availability rules (working hours, minimum
notice, buffers, limits per day, connected calendars) decide them, so the
agent never offers a time Calendly would refuse.

Bookings are made with Calendly's Scheduling API (``POST /invitees``): a real
booking, with Calendly's usual confirmation emails and calendar invites.
Calendly needs the invitee's email for it. Calendly's help centre (updated
4 Nov 2026) says the Scheduling API is on every plan, including Free; earlier
it needed a paid plan, so a 403 asking to upgrade is still answered with
``handoff: "plan_required"`` instead of pretending. Each booking carries
``tracking`` (``utm_source`` and the connection id in ``utm_content``) so the
Bookings page can list the ones this connection made.

Calendly has no API to move a booking, and this agent does not cancel any:
callers use the links in their Calendly email, or the team does it in
Calendly.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from pydantic import JsonValue

from fallcha_tools.core.provider import ConfigChoice, ConfigChoices
from fallcha_tools.providers.calendly.client import (
    CalendlyApiError,
    CalendlyClient,
    CalendlyError,
)
from fallcha_tools.providers.calendly.schemas import (
    AvailabilityResult,
    Booking,
    BookingResult,
    Handoff,
    Slot,
)
from fallcha_tools.providers.calendly.settings import (
    CalendlyConfig,
    event_type_uuid,
)
from fallcha_tools.providers.google_calendar.phone_numbers import (
    e164,
    region_for_timezone,
)
from fallcha_tools.providers.google_calendar.scheduling import (
    EVENING_HOUR,
    Window,
    bookable_window,
    resolve_window,
)
from fallcha_tools.providers.google_calendar.speech import join_spoken, say_time

Clock = Callable[[], datetime]

DEFAULT_DEADLINE_SECONDS = 5.0
# Calendly answers available times for ranges of up to 7 days per request in
# older docs and 31 days in the current ones: 7 works with both.
AVAILABLE_TIMES_SPAN = timedelta(days=7)
# The start of a range must not be in the past.
START_MARGIN = timedelta(minutes=1)
MORNING_END_HOUR = 12
TRACKING_SOURCE = "lightmove-ai"
TRACKING_MEDIUM = "voice-agent"
# The connection's account (URI, time zone) is re-read this often.
ACCOUNT_TTL = timedelta(minutes=30)
# Most scheduled events read for the Bookings page per request.
MAX_LISTED_EVENTS = 200
LIST_PAGE_SIZE = 100
INVITEE_READS_AT_ONCE = 5
MAX_EVENT_TYPE_PAGES = 3
_UUID_IN_URI = re.compile(r"/([A-Za-z0-9-]{1,64})$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Location kinds Calendly books with nothing more from the caller.
_PLAIN_LOCATIONS = frozenset(
    {
        "zoom_conference",
        "google_conference",
        "gotomeeting_conference",
        "microsoft_teams_conference",
        "webex_conference",
        "inbound_call",
    }
)
_TEXT_QUESTIONS = frozenset({"string", "text"})
_PHONE_WORDS = ("phone", "mobile", "number", "contact")

SAY_BOOKING_OFF = (
    "I can't book that on this call, but I can take your details and the team "
    "will get back to you to confirm."
)
SAY_FULLY_BOOKED = (
    "I'm sorry, there's nothing free to book at the moment. I can take your "
    "details and the team will get back to you."
)
SAY_ASK_EMAIL = (
    "I need a working email address to book that, as the confirmation goes "
    "there. Could you spell it for me again?"
)
SAY_ASK_PHONE = (
    "This appointment is a phone call, so I need the best number to call you "
    "on. What number should we use?"
)
SAY_UNCONFIRMED = (
    "I couldn't get a confirmation for that booking just now. If it went "
    "through, you'll get an email from Calendly. I'll take your details so "
    "the team can check and confirm it with you."
)
NOTHING_THEN = "Nothing free then, but"


@dataclass(frozen=True, slots=True)
class Account:
    """The Calendly user the connection acts as."""

    uri: str
    timezone: str | None
    email: str | None
    name: str | None


@dataclass
class AccountCache:
    """Accounts per connection, re-read after ``ACCOUNT_TTL``."""

    entries: dict[uuid.UUID, tuple[Account, datetime]] = field(default_factory=dict)

    def get(self, connection_id: uuid.UUID, now: datetime) -> Account | None:
        entry = self.entries.get(connection_id)
        if entry is None or entry[1] <= now:
            return None
        return entry[0]

    def put(self, connection_id: uuid.UUID, account: Account, now: datetime) -> None:
        self.entries[connection_id] = (account, now + ACCOUNT_TTL)


def calendly_time(moment: datetime) -> str:
    """UTC with a trailing Z, as Calendly wants it."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _uuid_of(uri: object) -> str | None:
    if not isinstance(uri, str):
        return None
    match = _UUID_IN_URI.search(uri)
    return match.group(1) if match else None


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def account_from(body: Mapping[str, Any]) -> Account:
    resource = body.get("resource")
    if not isinstance(resource, dict) or not isinstance(resource.get("uri"), str):
        raise CalendlyApiError("Calendly sent an unreadable account")
    return Account(
        uri=resource["uri"],
        timezone=_text(resource.get("timezone")),
        email=_text(resource.get("email")),
        name=_text(resource.get("name")),
    )


def _wanted(slot: datetime, part_of_day: str | None) -> bool:
    want = (part_of_day or "").strip().lower()
    if not want:
        return True
    if want.startswith("morning"):
        return slot.hour < MORNING_END_HOUR
    if want.startswith("evening") or want.startswith("night"):
        return slot.hour >= EVENING_HOUR
    if want.startswith("afternoon"):
        return MORNING_END_HOUR <= slot.hour < EVENING_HOUR
    return True


def _position(question: Mapping[str, Any]) -> int:
    position = question.get("position")
    return position if isinstance(position, int) else 0


def _duration(event_type: Mapping[str, Any]) -> str | None:
    minutes = event_type.get("duration")
    if not isinstance(minutes, int | float) or minutes <= 0:
        return None
    minutes = int(minutes)
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


@dataclass(frozen=True, slots=True)
class _Booking:
    """What ``POST /invitees`` needs beyond the time, or why it can't."""

    location: dict[str, JsonValue] | None = None
    answers: tuple[dict[str, JsonValue], ...] = ()
    refusal: str | None = None
    ask_phone: bool = False


@dataclass(frozen=True)
class CalendlyService:
    client: CalendlyClient
    config: CalendlyConfig
    connection_id: uuid.UUID
    clock: Clock
    accounts: AccountCache
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    # The number of the person on the call, from the call record; untrusted.
    contact_phone: str | None = None

    # -- the agent's functions ----------------------------------------------

    async def availability(
        self, relative_day: str | None, part_of_day: str | None
    ) -> AvailabilityResult:
        refusal = self._refusal()
        if refusal is not None:
            return AvailabilityResult(slots=[], say=refusal[1], handoff=refusal[0])
        cfg = self.config
        async with self._deadline():
            zone = await self._zone()
            now = self.clock().astimezone(zone)
            window = resolve_window(relative_day, now, cfg)
            wide = bookable_window(now, cfg)
            found = await self._find(window, part_of_day, zone)
            if not found and relative_day:
                wider = await self._find(wide, part_of_day, zone)
                if wider:
                    return AvailabilityResult(
                        slots=self._slots(wider),
                        say=f"{NOTHING_THEN} {join_spoken(wider)}",
                    )
            if not found and not await self._find(wide, None, zone, limit=1):
                return AvailabilityResult(
                    slots=[], say=SAY_FULLY_BOOKED, handoff="fully_booked"
                )
            return AvailabilityResult(slots=self._slots(found), say=join_spoken(found))

    async def book(
        self,
        slot_id: str,
        caller_name: str,
        caller_email: str,
        caller_phone: str | None = None,
        reason: str | None = None,
    ) -> BookingResult:
        refusal = self._refusal()
        if refusal is not None:
            return BookingResult(booked=False, say=refusal[1], handoff=refusal[0])
        email = caller_email.strip().replace(" ", "")
        if not _EMAIL.fullmatch(email):
            return BookingResult(booked=False, say=SAY_ASK_EMAIL, needs_email=True)
        event_type = self._event_type_uri()
        posted = False
        try:
            async with self._deadline():
                zone = await self._zone()
                slot = self._parse_slot(slot_id, zone)
                details = self._booking_details(
                    await self._event_type(),
                    phone=self._phone(caller_phone, zone),
                    reason=_text(reason),
                )
                if details.ask_phone:
                    return BookingResult(booked=False, say=SAY_ASK_PHONE)
                if details.refusal is not None:
                    logger.info(
                        "Calendly connection {} cannot book: {}",
                        self.connection_id,
                        details.refusal,
                    )
                    return self._handoff("cannot_book")
                body: dict[str, JsonValue] = {
                    "event_type": event_type,
                    "start_time": calendly_time(slot),
                    "invitee": {
                        "name": caller_name.strip()[:200],
                        "email": email,
                        "timezone": zone.key,
                    },
                    # Calendly refuses a tracking object without all six
                    # fields (each may be null).
                    "tracking": {
                        "utm_campaign": None,
                        "utm_source": TRACKING_SOURCE,
                        "utm_medium": TRACKING_MEDIUM,
                        "utm_content": str(self.connection_id),
                        "utm_term": None,
                        "salesforce_uuid": None,
                    },
                }
                if details.location is not None:
                    body["location"] = details.location
                if details.answers:
                    body["questions_and_answers"] = list(details.answers)
                posted = True
                created = await self.client.post("/invitees", body)
        except TimeoutError:
            if posted:
                return self._handoff("unconfirmed", SAY_UNCONFIRMED)
            raise CalendlyApiError("Calendly did not respond in time") from None
        except CalendlyApiError as exc:
            if not posted:
                raise
            if exc.status is None:
                # No answer (timeout, dropped connection): it may have been
                # booked, so it must not be tried again or denied.
                return self._handoff("unconfirmed", SAY_UNCONFIRMED)
            return await self._refused(exc, slot_id)
        resource = created.get("resource")
        event_id = (
            _uuid_of(resource.get("event")) if isinstance(resource, dict) else None
        )
        if event_id is None:
            # Created (201) but unreadable: never claim a booking we can't name.
            logger.warning(
                "Calendly booked for {} without an event", self.connection_id
            )
            return self._handoff("unconfirmed", SAY_UNCONFIRMED)
        local = slot.astimezone(zone)
        return BookingResult(
            booked=True,
            event_id=event_id,
            starts_at=local.isoformat(),
            say=(
                f"That is booked in for {say_time(local)}. Calendly will email "
                "the details to you."
            ),
        )

    # -- admin ----------------------------------------------------------------

    async def check_access(self) -> tuple[str, str | None]:
        """A message for the connection test, and the account label."""
        async with self._deadline():
            account = await self._account(fresh=True)
            label = account.email or account.name
            if self.config.event_type is None:
                return (
                    "Calendly is connected. Choose which Calendly event callers book.",
                    label,
                )
            event_type = await self._event_type()
        name = _text(event_type.get("name")) or "your event"
        if event_type.get("active") is False:
            return (
                f"Calendly is connected, but '{name}' is switched off in Calendly.",
                label,
            )
        return (f"Calendly is connected. Callers book '{name}'.", label)

    async def choices(self) -> ConfigChoices:
        """The account's active event types, for the owner to pick one."""
        async with self._deadline():
            account = await self._account()
            found: list[ConfigChoice] = []
            params = {"user": account.uri, "active": "true", "count": "100"}
            for _ in range(MAX_EVENT_TYPE_PAGES):
                body = await self.client.get("/event_types", params)
                for item in body.get("collection") or []:
                    choice = self._choice(item)
                    if choice is not None:
                        found.append(choice)
                token = _text((body.get("pagination") or {}).get("next_page_token"))
                if token is None:
                    break
                params = {**params, "page_token": token}
        return ConfigChoices(field="event_type", choices=found)

    async def list_bookings(self, start: datetime, end: datetime) -> list[Booking]:
        """Bookings this connection made in [start, end), read from Calendly:
        scheduled events of the chosen event type whose invitee carries this
        connection's tracking."""
        uri = self.config.event_type
        if uri is None:
            return []
        account = await self._account()
        events: list[Mapping[str, Any]] = []
        params = {
            "user": account.uri,
            "min_start_time": calendly_time(start),
            "max_start_time": calendly_time(end),
            "count": str(LIST_PAGE_SIZE),
            "sort": "start_time:asc",
        }
        while len(events) < MAX_LISTED_EVENTS:
            body = await self.client.get("/scheduled_events", params)
            events.extend(
                e
                for e in body.get("collection") or []
                if isinstance(e, dict) and e.get("event_type") == uri
            )
            token = _text((body.get("pagination") or {}).get("next_page_token"))
            if token is None:
                break
            params = {**params, "page_token": token}
        limit = asyncio.Semaphore(INVITEE_READS_AT_ONCE)

        async def ours(event: Mapping[str, Any]) -> Booking | None:
            async with limit:
                return await self._booking_of(event)

        found = await asyncio.gather(*(ours(e) for e in events[:MAX_LISTED_EVENTS]))
        return [b for b in found if b is not None]

    # -- helpers --------------------------------------------------------------

    def _refusal(self) -> tuple[Handoff, str] | None:
        if not self.config.ai_booking_enabled:
            return "booking_off", SAY_BOOKING_OFF
        if self.config.event_type is None:
            return "not_set_up", SAY_BOOKING_OFF
        return None

    @staticmethod
    def _handoff(handoff: Handoff, say: str = SAY_BOOKING_OFF) -> BookingResult:
        return BookingResult(booked=False, say=say, handoff=handoff)

    def _event_type_uri(self) -> str:
        uri = self.config.event_type
        assert uri is not None  # checked by _refusal
        return uri

    async def _event_type(self) -> Mapping[str, Any]:
        uuid_ = event_type_uuid(self._event_type_uri())
        body = await self.client.get(f"/event_types/{uuid_}")
        resource = body.get("resource")
        if not isinstance(resource, dict):
            raise CalendlyApiError("Calendly sent an unreadable event type")
        return resource

    async def _account(self, *, fresh: bool = False) -> Account:
        now = self.clock()
        cached = None if fresh else self.accounts.get(self.connection_id, now)
        if cached is not None:
            return cached
        account = account_from(await self.client.get("/users/me"))
        self.accounts.put(self.connection_id, account, now)
        return account

    async def _zone(self) -> ZoneInfo:
        name = self.config.timezone
        if name is None:
            name = (await self._account()).timezone or "UTC"
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    def _slots(self, found: Sequence[datetime]) -> list[Slot]:
        return [Slot(id=slot.isoformat(), say=say_time(slot)) for slot in found]

    async def _find(
        self,
        window: Window,
        part_of_day: str | None,
        zone: ZoneInfo,
        *,
        limit: int | None = None,
    ) -> list[datetime]:
        """Up to ``limit`` free start times in ``window`` (local, in order)."""
        limit = limit or self.config.max_slots_returned
        start = max(window[0], self.clock() + START_MARGIN)
        end = window[1]
        if start >= end:
            return []
        chunks: list[Window] = []
        cursor = start
        while cursor < end:
            chunks.append((cursor, min(cursor + AVAILABLE_TIMES_SPAN, end)))
            cursor = chunks[-1][1]
        answers = await asyncio.gather(*(self._free_times(c) for c in chunks))
        found: list[datetime] = []
        for (chunk_start, chunk_end), times in zip(chunks, answers, strict=True):
            for moment in times:
                local = moment.astimezone(zone)
                if chunk_start <= moment < chunk_end and _wanted(local, part_of_day):
                    found.append(local)
        found = sorted(set(found))
        return found[:limit]

    async def _free_times(self, window: Window) -> list[datetime]:
        body = await self.client.get(
            "/event_type_available_times",
            {
                "event_type": self._event_type_uri(),
                "start_time": calendly_time(window[0]),
                "end_time": calendly_time(window[1]),
            },
        )
        times = []
        for item in body.get("collection") or []:
            if not isinstance(item, dict) or item.get("status") != "available":
                continue
            moment = _parse_time(item.get("start_time"))
            if moment is not None:
                times.append(moment)
        return times

    def _parse_slot(self, slot_id: str, zone: ZoneInfo) -> datetime:
        slot = _parse_time(slot_id.strip())
        if slot is None:
            try:
                slot = datetime.fromisoformat(slot_id.strip()).replace(tzinfo=zone)
            except ValueError:
                raise CalendlyError(
                    "slot_id must be copied from check_appointment_availability"
                ) from None
        return slot

    def _phone(self, said: str | None, zone: ZoneInfo) -> str | None:
        """The caller's number, E.164 when it parses (Calendly wants that)."""
        number = _text(said) or _text(self.contact_phone)
        if number is None:
            return None
        region = self.config.phone_region or region_for_timezone(zone.key)
        return e164(number, region) or number

    @staticmethod
    def _booking_details(
        event_type: Mapping[str, Any], *, phone: str | None, reason: str | None
    ) -> _Booking:
        location: dict[str, JsonValue] | None = None
        locations = [
            loc for loc in event_type.get("locations") or [] if isinstance(loc, dict)
        ]
        if locations and event_type.get("pooling_type") != "round_robin":
            needs_phone = False
            for loc in locations:
                kind = loc.get("kind")
                if kind in _PLAIN_LOCATIONS:
                    location = {"kind": kind}
                elif kind in ("physical", "custom") and _text(loc.get("location")):
                    location = {"kind": kind, "location": _text(loc.get("location"))}
                elif kind == "outbound_call":
                    if phone is None:
                        needs_phone = True
                        continue
                    location = {"kind": kind, "location": phone}
                if location is not None:
                    break
            if location is None:
                if needs_phone:
                    return _Booking(ask_phone=True)
                return _Booking(refusal="its location needs the caller to type one")
        answers: list[dict[str, JsonValue]] = []
        phone_given = reason_given = False
        questions = [
            q for q in event_type.get("custom_questions") or [] if isinstance(q, dict)
        ]
        for question in sorted(questions, key=_position):
            if question.get("enabled") is False:
                continue
            name = question.get("name")
            position = question.get("position")
            if not isinstance(name, str) or not isinstance(position, int):
                continue
            kind = question.get("type")
            asks_phone = kind == "phone_number" or (
                kind in _TEXT_QUESTIONS
                and any(word in name.lower() for word in _PHONE_WORDS)
            )
            answer: str | None = None
            if asks_phone and phone and not phone_given:
                answer, phone_given = phone, True
            elif (
                kind in _TEXT_QUESTIONS
                and not asks_phone
                and reason
                and not reason_given
            ):
                answer, reason_given = reason, True
            if answer is not None:
                answers.append(
                    {"question": name, "answer": answer, "position": position}
                )
            elif question.get("required") is True:
                return _Booking(
                    refusal=f"a required question it cannot answer ({kind})"
                )
        return _Booking(location=location, answers=tuple(answers))

    async def _refused(self, exc: CalendlyApiError, slot_id: str) -> BookingResult:
        """Calendly said no to ``POST /invitees``: say why, honestly."""
        if exc.plan_required:
            logger.info(
                "Calendly connection {} was asked to upgrade to book",
                self.connection_id,
            )
            return self._handoff("plan_required")
        if exc.status == 400 and any("email" in f for f in exc.fields):
            return BookingResult(booked=False, say=SAY_ASK_EMAIL, needs_email=True)
        if exc.status in (400, 404, 409, 422):
            # Most often the time was just taken: offer others if so.
            try:
                async with self._deadline():
                    zone = await self._zone()
                    slot = self._parse_slot(slot_id, zone)
                    now = self.clock().astimezone(zone)
                    wide = bookable_window(now, self.config)
                    others = await self._find(wide, None, zone, limit=50)
            except (CalendlyError, TimeoutError):
                return self._handoff("cannot_book")
            if slot.astimezone(zone) not in others:
                alternatives = others[: self.config.max_slots_returned]
                if not alternatives:
                    return self._handoff("fully_booked", SAY_FULLY_BOOKED)
                return BookingResult(
                    booked=False,
                    slots=self._slots(alternatives),
                    say=f"That one has just gone. {join_spoken(alternatives)}",
                )
        return self._handoff("cannot_book")

    def _choice(self, item: object) -> ConfigChoice | None:
        if not isinstance(item, dict):
            return None
        uri = item.get("uri")
        name = _text(item.get("name"))
        if not isinstance(uri, str) or name is None:
            return None
        try:
            event_type_uuid(uri)
        except ValueError:
            return None
        parts = [p for p in (_duration(item),) if p]
        if item.get("kind") == "group":
            parts.append("group event")
        details = self._booking_details(item, phone="+10000000000", reason="-")
        warning = None
        if details.refusal is not None:
            warning = (
                "Your agent can't book this one: it asks callers for something "
                "only they can type in Calendly (a location, or a required "
                "question). Pick another, or change it in Calendly."
            )
        return ConfigChoice(
            value=uri,
            label=name,
            config={"event_type": uri, "event_type_name": name},
            detail=" · ".join(parts) or None,
            warning=warning,
        )

    async def _booking_of(self, event: Mapping[str, Any]) -> Booking | None:
        uuid_ = _uuid_of(event.get("uri"))
        start = _parse_time(event.get("start_time"))
        end = _parse_time(event.get("end_time"))
        if uuid_ is None or start is None or end is None:
            return None
        body = await self.client.get(
            f"/scheduled_events/{uuid_}/invitees", {"count": "10"}
        )
        for invitee in body.get("collection") or []:
            if not isinstance(invitee, dict):
                continue
            tracking = invitee.get("tracking")
            if not isinstance(tracking, dict):
                continue
            if tracking.get("utm_source") != TRACKING_SOURCE or tracking.get(
                "utm_content"
            ) != str(self.connection_id):
                continue
            phone = None
            reason = None
            for qa in invitee.get("questions_and_answers") or []:
                if not isinstance(qa, dict):
                    continue
                question = str(qa.get("question") or "").lower()
                answer = _text(qa.get("answer"))
                if any(word in question for word in _PHONE_WORDS):
                    phone = phone or answer
                else:
                    reason = reason or answer
            location = event.get("location")
            if (
                phone is None
                and isinstance(location, dict)
                and location.get("type") == "outbound_call"
            ):
                phone = _text(location.get("location"))
            cancelled = (
                event.get("status") == "canceled" or invitee.get("status") == "canceled"
            )
            return Booking(
                event_id=uuid_,
                start=start,
                end=end,
                status="cancelled" if cancelled else "confirmed",
                caller_name=_text(invitee.get("name")),
                caller_phone=phone,
                reason=reason,
                created_at=_parse_time(invitee.get("created_at")),
            )
        return None

    @asynccontextmanager
    async def _deadline(self) -> AsyncIterator[None]:
        async with asyncio.timeout(self.deadline_seconds):
            yield


ServiceFactory = Callable[..., CalendlyService]

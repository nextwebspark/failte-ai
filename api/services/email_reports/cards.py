"""The report cards the owner ticked for the email, turned into blocks the
email can draw with tables only: numbers, bars and short lists.

The numbers are the page's own (``report_cards.cards``), in the owner's
order. Pure: ``content.load_report`` does the reading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from api.services.email_reports.formatting import (
    change_text,
    clock,
    euro,
    hour_label,
    mask_phone,
    plural,
    short_day,
)
from api.services.email_reports.periods import Frequency
from api.services.report_cards.catalogue import Card, CardSize, PackSpec

# The reason colours of Home's "What callers wanted" (CallersWantedChart):
# the template's booking reason, questions, changes, its own fourth; Other
# grey, "Not reviewed yet" pale grey.
REASON_SLOTS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a5cd1")
OTHER_COLOUR = "#9aa1ad"
NOT_REVIEWED_COLOUR = "#dfe3e9"
_KEY_SLOT = {
    "reservations": 0,
    "appointments": 0,
    "new_job": 0,
    "viewings": 0,
    "questions": 1,
    "property_questions": 1,
    "changes": 2,
    "existing_job": 2,
    "takeaway": 3,
    "urgent": 3,
    "walk_ins": 3,
    "selling": 3,
    "speak_to_someone": 3,
    "product_stock": 0,
    "orders_delivery": 1,
    "returns_faults": 2,
    "servicing": 3,
    "technical_advice": 4,
}
_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

FOLLOW_UP_KINDS = {
    "callback": "Call back",
    "transfer_not_answered": "Transfer not answered",
    "repeat_caller": "Rang more than once",
    "unanswered_question": "Couldn't answer",
    "time_was_full": "Time was full",
}


@dataclass(frozen=True, slots=True)
class Tile:
    label: str
    value: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class BarRow:
    label: str
    count: int
    # The bar's colour; None: the brand green.
    colour: str | None = None
    # Shown instead of the count, e.g. "Closed".
    value: str | None = None


@dataclass(frozen=True, slots=True)
class ListRow:
    title: str
    detail: str | None = None
    meta: str | None = None


@dataclass(frozen=True, slots=True)
class EmailBlock:
    # "calls" (the call tiles), "follow_ups" (the open list), "when" (calls by
    # hour or day), or a generic "tiles", "bars", "list" or "note".
    kind: str
    key: str
    title: str
    tiles: tuple[Tile, ...] = ()
    bars: tuple[BarRow, ...] = ()
    rows: tuple[ListRow, ...] = ()
    note: str | None = None


def reason_colours(keys: Sequence[str]) -> dict[str, str]:
    """Each reason's colour, as Home's chart gives it."""
    colours: dict[str, str] = {}
    used: set[int] = set()
    for key in keys:
        slot = _KEY_SLOT.get(key)
        if slot is not None and slot not in used:
            colours[key] = REASON_SLOTS[slot]
            used.add(slot)
    for key in keys:
        if key in colours:
            continue
        if key == "other":
            colours[key] = OTHER_COLOUR
        elif key == "not_reviewed":
            colours[key] = NOT_REVIEWED_COLOUR
        else:
            free = next((i for i in range(len(REASON_SLOTS)) if i not in used), None)
            colours[key] = REASON_SLOTS[free] if free is not None else OTHER_COLOUR
            if free is not None:
                used.add(free)
    return colours


def _hours(start: int, end: int) -> str:
    """ "5-7 pm", "11 am-1 pm"."""
    a, b = start % 24, end % 24
    a_suffix, b_suffix = ("am" if a < 12 else "pm"), ("am" if b < 12 else "pm")
    a12, b12 = a % 12 or 12, b % 12 or 12
    if a_suffix == b_suffix:
        return f"{a12}–{b12} {b_suffix}"
    return f"{a12} {a_suffix}–{b12} {b_suffix}"


def _waited(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    if minutes < 60:
        return plural(minutes, "minute")
    hours, rest = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return plural(hours // 24, "day")


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _change(card: Mapping[str, Any], frequency: Frequency) -> str | None:
    return change_text(card.get("change"), frequency)


def _kpi(
    key: str,
    title: str,
    card: Mapping[str, Any],
    frequency: Frequency,
    tz: ZoneInfo,
) -> Tile | None:
    if key in (Card.BOOKINGS_TAKEN, Card.APPOINTMENTS_BOOKED):
        share = card.get("percent_of_calls")
        note = _change(card, frequency) or (
            f"{share}% of calls ended in a booking" if share is not None else None
        )
        return Tile(title, str(card["count"]), note)
    if key == Card.COVERS_BOOKED:
        average = card.get("average_party")
        note = _change(card, frequency) or (
            f"Average table of {average}" if average is not None else None
        )
        return Tile(title, str(card["covers"]), note)
    if key == Card.TABLES_FULL:
        days = [_WEEKDAYS[d][:3] for d in card.get("mostly_days") or []]
        hour = card.get("mostly_hour")
        when = " and ".join(days)
        if hour is not None:
            when = f"{when} {_hours(hour, hour + 1)}".strip()
        note = f"Mostly {when}" if when else None
        value = str(card["count"])
        if card.get("covers"):
            value += f" · {plural(card['covers'], 'cover')}"
        return Tile(title, value, note)
    if key in (
        Card.TAKEAWAY,
        Card.EMERGENCIES,
        Card.CHANGES,
        Card.JOBS_QUOTES,
        Card.PRODUCT_ENQUIRIES,
        Card.ORDERS_DELIVERY,
        Card.RETURNS,
        Card.SERVICING_REQUESTS,
    ):
        waiting = card.get("needed_person") or 0
        note = _change(card, frequency) or (
            f"{waiting} needed someone from your team" if waiting else None
        )
        return Tile(title, str(card["count"]), note)
    if key == Card.AFTER_HOURS_CALLOUTS:
        if not card.get("hours_set"):
            return Tile(title, "–", "Set your opening hours as times to count these")
        return Tile(title, str(card["count"]), _change(card, frequency))
    if key in (Card.SORTED_BY_AGENT, Card.PASSED_ON):
        percent = card.get("percent")
        note = f"{percent}% of calls" if percent is not None else None
        return Tile(title, str(card["count"]), note)
    if key in (Card.BOOKINGS_VALUE, Card.APPOINTMENTS_VALUE, Card.JOBS_VALUE):
        unit = str(card["unit"])
        what = "average spend" if unit == "cover" else "average value"
        note = (
            f"Estimate: {plural(int(card['units']), unit)} × your "
            f"{_money(card['average'])} {what}"
        )
        return Tile(title, _money(card["value"]), note)
    return None


def _money(value: Decimal | float | str) -> str:
    amount = Decimal(str(value))
    if amount == amount.to_integral_value():
        return f"€{int(amount):,}"
    return euro(amount)


def email_blocks(
    *,
    pack: PackSpec,
    order: Sequence[str],
    cards: Mapping[str, Any],
    frequency: Frequency,
    tz: ZoneInfo,
) -> list[EmailBlock]:
    """The ticked cards (*order*) as email blocks. Number cards next to each
    other share one grid of tiles; a card with nothing to show is left out
    (a money estimate before the owner gives an average, takeaway for a
    business without it)."""
    blocks: list[EmailBlock] = []
    tiles: list[Tile] = []

    def flush() -> None:
        if tiles:
            blocks.append(EmailBlock("tiles", "kpis", "", tiles=tuple(tiles)))
            tiles.clear()

    for key in order:
        spec = pack.spec(key)
        card = cards.get(key)
        if spec is None or card is None:
            continue
        if key == Card.CALLS_ANSWERED:
            flush()
            blocks.append(EmailBlock("calls", key, spec.title))
            continue
        if spec.size == CardSize.KPI:
            tile = _kpi(key, spec.title, card, frequency, tz)
            if tile is not None:
                tiles.append(tile)
            continue
        flush()
        block = _panel(key, spec.title, card, frequency, tz)
        if block is not None:
            blocks.append(block)
    flush()
    return blocks


def _panel(
    key: str,
    title: str,
    card: Mapping[str, Any],
    frequency: Frequency,
    tz: ZoneInfo,
) -> EmailBlock | None:
    if key == Card.CALLERS_WANTED:
        series = card.get("series") or []
        if not series:
            return None
        colours = reason_colours([s["key"] for s in series])
        return EmailBlock(
            "bars",
            key,
            "What callers wanted",
            bars=tuple(
                BarRow(s["label"], s["count"], colours[s["key"]]) for s in series
            ),
            note="Day by day on your dashboard.",
        )
    if key == Card.BUSIEST_TIMES:
        tip = card.get("tip")
        note = None
        if tip:
            note = (
                f"{_WEEKDAYS[tip['weekday']]} {_hours(tip['start_hour'], tip['end_hour'])} "
                f"takes 1 in {tip['one_in']} of your calls. Worth having someone "
                "free to answer transfers then."
            )
        return EmailBlock("when", key, "Busiest times", note=note)
    if key == Card.FOLLOW_UPS:
        return EmailBlock("follow_ups", key, "Needs your attention")
    if key == Card.UNANSWERED_QUESTIONS:
        groups = card.get("groups") or []
        if not groups:
            return EmailBlock(
                "note", key, title, note="Your agent answered every question."
            )
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(BarRow(g["question"], g["count"]) for g in groups[:5]),
            note="Add an answer on your dashboard and your agent knows it next time.",
        )
    if key == Card.AFTER_HOURS:
        if not card.get("hours_set"):
            return EmailBlock(
                "note",
                key,
                title,
                note="Set your opening hours as times to see the calls that came in while you were closed.",
            )
        return EmailBlock(
            "tiles",
            key,
            title,
            tiles=(
                Tile("Calls while closed", str(card["calls"])),
                Tile("Bookings made", str(card["bookings"])),
                Tile("Left a number", str(card["callbacks"])),
            ),
        )
    if key == Card.AGENT_PERFORMANCE:
        if not card.get("calls"):
            return None
        percent = card.get("handled_percent")
        return EmailBlock(
            "bars",
            key,
            title,
            bars=(
                BarRow("Handled by your agent", card["handled"]),
                BarRow("Needed a person", card["needed_person"], "#eda100"),
                BarRow("No conversation", card["no_conversation"], OTHER_COLOUR),
            ),
            note=f"{percent}% handled start to finish, no staff needed."
            if percent is not None
            else None,
        )
    if key == Card.DAYS_FILLING:
        days = card.get("days") or []
        if not any(d["covers"] or d["bookings"] for d in days):
            return EmailBlock(
                "note", key, title, note="No bookings for the next two weeks yet."
            )
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(
                BarRow(
                    f"{_WEEKDAYS[_day(d['date']).weekday()][:3]} {_day(d['date']).day}",
                    d["covers"],
                    value="Closed" if d["closed"] and not d["covers"] else None,
                )
                for d in days
            ),
            note="Covers booked by phone, by the day they're for.",
        )
    if key == Card.SPECIAL_REQUESTS:
        tags = card.get("tags") or []
        if not tags:
            return None
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(BarRow(t["label"], t["count"]) for t in tags),
        )
    if key == Card.PATIENT_STATUS:
        rows = [
            BarRow("New patients", card["new"]),
            BarRow("Existing patients", card["existing"]),
        ]
        if card.get("other"):
            rows.append(BarRow("Something else", card["other"], OTHER_COLOUR))
        if not any(r.count for r in rows):
            return None
        return EmailBlock("bars", key, title, bars=tuple(rows))
    if key == Card.APPOINTMENT_TYPES:
        types = card.get("types") or []
        if not types:
            return None
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(
                BarRow(f"{t['label']} ({t['booked']} booked)", t["calls"])
                for t in types
            ),
        )
    if key == Card.TOP_PRODUCTS:
        products = card.get("products") or []
        if not products:
            return None
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(BarRow(p["label"], p["calls"]) for p in products),
        )
    if key == Card.EMERGENCIES_BY_HOUR:
        hours = card.get("hours") or []
        busy = [(h, n) for h, n in enumerate(hours) if n]
        if not busy:
            return EmailBlock("note", key, title, note="No emergencies in this period.")
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(BarRow(hour_label(h), n, "#eb6834") for h, n in busy),
        )
    if key == Card.AREAS:
        areas = card.get("areas") or []
        if not areas:
            return None
        note = None
        if card.get("unclear"):
            note = (
                f"{plural(card['unclear'], 'address', 'addresses')} couldn't be placed."
            )
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(BarRow(a["label"], a["count"]) for a in areas),
            note=note,
        )
    if key in (Card.CALLBACKS_WAITING, Card.WAITING_FOR_TEAM):
        items = card.get("items") or []
        if not items:
            return EmailBlock(
                "note", key, title, note="Nobody is waiting for a call back."
            )
        rows = []
        for item in items:
            when = item["created_at"]
            when = when if isinstance(when, datetime) else datetime.fromisoformat(when)
            local = when.astimezone(tz)
            who = item.get("caller_name") or mask_phone(item.get("caller_number"))
            meta = " · ".join(
                x
                for x in (item.get("area"), f"{short_day(local)}, {clock(local)}")
                if x
            )
            rows.append(ListRow(who, item.get("about"), meta))
        return EmailBlock(
            "list",
            key,
            title,
            rows=tuple(rows),
            note=f"Waiting longest: {_waited(card.get('oldest_minutes'))}."
            if card.get("oldest_minutes") is not None
            else None,
        )
    if key == Card.ISSUES_BY_TYPE:
        types = card.get("types") or []
        if not types:
            return None
        colours = reason_colours([t["key"] for t in types])
        return EmailBlock(
            "bars",
            key,
            title,
            bars=tuple(
                BarRow(
                    f"{t['label']}: {t['sorted']} sorted, {t['passed_on']} passed on",
                    t["count"],
                    colours[t["key"]],
                )
                for t in types
            ),
        )
    if key == Card.CALL_SPIKES:
        spikes = card.get("spikes") or []
        if not spikes:
            return EmailBlock(
                "note", key, title, note="No hour had far more calls than usual."
            )
        rows = []
        for spike in spikes:
            at = spike["at"]
            at = at if isinstance(at, datetime) else datetime.fromisoformat(at)
            local = at.astimezone(tz)
            rows.append(
                ListRow(
                    f"{short_day(local)}, {_hours(local.hour, local.hour + 1)}",
                    f"{plural(spike['calls'], 'call')} (usually {spike['usual']})",
                )
            )
        return EmailBlock("list", key, title, rows=tuple(rows))
    if key == Card.REPEAT_CALLERS:
        items = card.get("items") or []
        if not items:
            return EmailBlock("note", key, title, note="Nobody rang more than once.")
        return EmailBlock(
            "list",
            key,
            title,
            rows=tuple(
                ListRow(
                    i.get("caller_name") or mask_phone(i.get("caller_number")),
                    f"Rang {i['calls']} times"
                    + ("" if i["reached"] else ", last call reached nobody"),
                )
                for i in items
            ),
        )
    return None

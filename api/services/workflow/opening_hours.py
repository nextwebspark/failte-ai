"""An agent's structured opening hours (``OpeningHours``): how they are
stored, said and checked.

They are kept with the agent's other business facts (its template context
variables), as JSON text under ``opening_hours_schedule``, so they travel
with the agent's versions and reach every call's ``initial_context`` like
the other facts, with no table of their own. Saving them also writes:

* ``opening_hours``: the plain-English sentence the prompts already read
  (``{{initial_context.opening_hours}}``), generated from the times, e.g.
  "Tuesday to Sunday 12 to 3 pm and 5 to 10 pm, closed Monday";
* ``timezone``: the business's zone, which the agent's date line and Home
  already read.

Agents that only have free-text hours keep that text; nothing here guesses
times from it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import ValidationError

from api.schemas.appointment_hours import Weekday
from api.schemas.opening_hours import DAY_MINUTES, OpeningHours, OpenRange
from api.services.workflow.business_facts import BusinessFactsError

SCHEDULE_KEY = "opening_hours_schedule"
TEXT_KEY = "opening_hours"
TIMEZONE_KEY = "timezone"

# What the transfer tool returns when it doesn't ring anyone because the
# business is closed. Shaped like a transfer nobody answered, so the agent
# carries on as it does then (takes a message); ``reason`` tells the two
# apart for the call's outcome (see ``call_notifications.outcome``).
CLOSED_REASON = "closed"


def closed_transfer_result() -> dict[str, str]:
    return {
        "status": "failed",
        "action": "transfer_failed",
        "reason": CLOSED_REASON,
        "message": (
            "Nobody from the team is available right now: it's outside the "
            "business's opening hours, so the call was not put through. Don't "
            "try to transfer again on this call. Tell the caller the team "
            "isn't available at the moment and offer to take a message: their "
            "name, the best number to call them back on and what it's about."
        ),
    }


# ------------------------------------------------------------------ storage


def stored_opening_hours(facts: Mapping[str, Any] | None) -> OpeningHours | None:
    """The agent's structured opening hours, or None when it has none (or
    the stored value can't be read, which is logged and treated as none)."""
    return parse_opening_hours((facts or {}).get(SCHEDULE_KEY))


def parse_opening_hours(raw: Any) -> OpeningHours | None:
    """A stored ``opening_hours_schedule`` value (JSON text, or already a
    dict) as ``OpeningHours``; None when unset or unreadable."""
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return OpeningHours.model_validate(value)
    except (ValueError, TypeError, ValidationError) as exc:
        logger.warning(f"Unreadable {SCHEDULE_KEY} ignored: {type(exc).__name__}")
        return None


def opening_hours_facts(hours: OpeningHours | None) -> dict[str, str | None]:
    """The facts saving *hours* writes. None removes the times only: the
    sentence they generated stays as the agent's free-text hours."""
    if hours is None:
        return {SCHEDULE_KEY: None}
    return {
        SCHEDULE_KEY: hours.model_dump_json(),
        TEXT_KEY: describe_opening_hours(hours),
        TIMEZONE_KEY: hours.timezone,
    }


def opening_hours_updates(
    facts: Mapping[str, Any] | None,
    text_updates: Mapping[str, str | None],
    *,
    has_hours_fact: bool,
    hours_sent: bool,
    hours: OpeningHours | None,
) -> dict[str, str | None]:
    """An owner's save, cleaned text facts plus any opening hours, as the
    facts to write.

    With times set, the ``opening_hours`` text follows them: a text edit in
    the same save is dropped, and one on its own is refused (it would be
    overwritten by the times on their next change, and say something else
    than the times until then). Clearing the times keeps the text.
    """
    updates = dict(text_updates)
    if hours_sent:
        if hours is not None and not has_hours_fact:
            raise BusinessFactsError("This agent has no opening hours to set.")
        if hours is not None:
            updates.pop(TEXT_KEY, None)
        updates.update(opening_hours_facts(hours))
        return updates
    if TEXT_KEY in updates and stored_opening_hours(facts) is not None:
        if updates[TEXT_KEY] != (facts or {}).get(TEXT_KEY):
            raise BusinessFactsError(
                "Your opening hours are set as times. Change the times, or "
                "switch back to writing them out."
            )
        updates.pop(TEXT_KEY)
    return updates


# ------------------------------------------------------------------- words
# (Day wording as in ``appointment_hours``; repeated here so the call engine,
# which imports this module, doesn't load the calendar integration.)


def _join(items: Sequence[str]) -> str:
    """Join as in "A", "A and B", "A, B and C"."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _days_phrase(days: Sequence[Weekday]) -> str:
    """ "every day", "Tuesday to Sunday", "Saturday and Sunday", "Monday and
    Wednesday to Friday": three or more days in a row read as a range."""
    if set(days) == set(Weekday):
        return "every day"
    runs: list[list[Weekday]] = []
    for day in sorted(set(days)):
        if runs and day == runs[-1][-1] + 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    parts: list[str] = []
    for run in runs:
        if len(run) >= 3:
            parts.append(f"{run[0].name.capitalize()} to {run[-1].name.capitalize()}")
        else:
            parts.extend(day.name.capitalize() for day in run)
    return _join(parts)


def _clock(minutes: int) -> tuple[str, str]:
    """(number, suffix): 9:30 → ("9:30", "am"), 17:00 → ("5", "pm")."""
    hour, minute = divmod(minutes % DAY_MINUTES, 60)
    number = str(hour % 12 or 12) + (f":{minute:02d}" if minute else "")
    return number, "am" if hour < 12 else "pm"


def _time(minutes: int) -> str:
    if minutes % DAY_MINUTES == 0:
        return "midnight"
    number, suffix = _clock(minutes)
    return f"{number} {suffix}"


def _range_phrase(open_range: OpenRange) -> str:
    """ "12 to 3 pm", "11 am to 3 pm", "6 pm to 2 am", "5 pm to midnight"."""
    start, end = open_range.start, open_range.end
    if (start, end) == (0, DAY_MINUTES):
        return "open 24 hours"
    if end % DAY_MINUTES != 0 and start % DAY_MINUTES != 0 and end < DAY_MINUTES:
        (open_number, open_suffix), (close_number, close_suffix) = (
            _clock(start),
            _clock(end),
        )
        if open_suffix == close_suffix:
            return f"{open_number} to {close_number} {close_suffix}"
    return f"{_time(start)} to {_time(end)}"


def _day_hours(ranges: Sequence[OpenRange]) -> str:
    return _join([_range_phrase(r) for r in ranges])


def describe_opening_hours(hours: OpeningHours) -> str:
    """The hours in plain English, as the agent says them, e.g. "Tuesday to
    Sunday 12 to 3 pm and 5 to 10 pm, closed Monday"; days with the same
    times are said together. The owner's note follows as its own sentence."""
    groups: dict[tuple[OpenRange, ...], list[Weekday]] = {}
    closed: list[Weekday] = []
    for day, ranges in zip(Weekday, hours.days):
        if ranges:
            groups.setdefault(tuple(ranges), []).append(day)
        else:
            closed.append(day)
    parts = [
        f"{_days_phrase(days)} {_day_hours(ranges)}" for ranges, days in groups.items()
    ]
    if closed:
        parts.append(f"closed {_days_phrase(closed)}")
    text = ", ".join(parts)
    text = text[:1].upper() + text[1:]
    if hours.note:
        note = hours.note
        text = f"{text}. {note[:1].upper()}{note[1:]}"
    return text


# ------------------------------------------------------------------- times


def is_open(hours: OpeningHours, at: datetime) -> bool:
    """Whether the business is open at *at* (a naive time is UTC), read on
    the wall clock in its zone: a range runs from its opening time up to,
    not including, its closing time, and one past midnight goes on into the
    next day."""
    moment = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    local = moment.astimezone(ZoneInfo(hours.timezone))
    minute = local.hour * 60 + local.minute
    today = local.weekday()
    if any(r.start <= minute < r.end for r in hours.days[today]):
        return True
    yesterday = (today - 1) % 7
    return any(minute + DAY_MINUTES < r.end for r in hours.days[yesterday])


def transfer_closed(
    facts: Mapping[str, Any] | None, now: datetime | None = None
) -> bool:
    """The transfer gate: True when the agent has structured opening hours,
    passes calls only while open, and the business is closed now. Without
    structured hours a transfer is always tried."""
    hours = stored_opening_hours(facts)
    if hours is None or not hours.transfer_only_when_open:
        return False
    return not is_open(hours, now or datetime.now(UTC))


def is_after_hours(
    agent_id: int, arrived: datetime, hours_by_agent: Mapping[int, OpeningHours]
) -> bool:
    """Whether a call to *agent_id* arrived while its business was closed.
    False for agents without structured hours: nothing is guessed."""
    hours = hours_by_agent.get(agent_id)
    return hours is not None and not is_open(hours, arrived)


def after_hours_count(
    calls: Sequence[tuple[int, datetime]],
    hours_by_agent: Mapping[int, OpeningHours],
) -> int:
    """How many of the calls, ``(agent id, arrived at)``, arrived while their
    agent's business was closed. Calls of agents without structured hours
    are not counted."""
    return sum(
        1
        for agent_id, arrived in calls
        if is_after_hours(agent_id, arrived, hours_by_agent)
    )


# How finely open time is read when the day is shown in another zone than
# the business's own (rare: Home shows the workspace's zone for all agents).
_OTHER_ZONE_STEP = 5


def open_minutes(hours: OpeningHours, day: date, zone: ZoneInfo) -> list[bool]:
    """For each of the 1440 wall-clock minutes of *day* in *zone*, whether
    the business is open, by the same rule as ``is_open`` (yesterday's range
    that runs past midnight included). In the business's own zone it is read
    straight from the times; in another zone it is checked every few
    minutes."""
    if zone.key == hours.timezone:
        minutes = [False] * DAY_MINUTES
        weekday = day.weekday()
        for r in hours.days[weekday]:
            for m in range(r.start, min(r.end, DAY_MINUTES)):
                minutes[m] = True
        for r in hours.days[(weekday - 1) % 7]:
            for m in range(0, max(0, r.end - DAY_MINUTES)):
                minutes[m] = True
        return minutes
    midnight = datetime.combine(day, time.min, tzinfo=zone)
    minutes = []
    for start in range(0, DAY_MINUTES, _OTHER_ZONE_STEP):
        at = midnight + timedelta(minutes=start)
        minutes.extend([is_open(hours, at)] * _OTHER_ZONE_STEP)
    return minutes[:DAY_MINUTES]


def minute_ranges(minutes: Sequence[bool]) -> list[tuple[int, int]]:
    """Runs of open minutes as ``(start, end)`` minute pairs, end exclusive:
    [F, T, T, F] → [(1, 3)]."""
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for m, value in enumerate(minutes):
        if value and start is None:
            start = m
        elif not value and start is not None:
            ranges.append((start, m))
            start = None
    if start is not None:
        ranges.append((start, len(minutes)))
    return ranges

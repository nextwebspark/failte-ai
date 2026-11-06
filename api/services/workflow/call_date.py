"""Today's date for the agent, so "this Friday" or "tomorrow" lands on the right day.

Language models don't know the date. Without this line an agent works dates
out from its training data and can save a booking in the wrong year. The line
goes into every agent's instructions and into the step that saves the caller's
details, whatever the agent's own wording says.

The business's timezone comes from the agent's ``timezone`` business fact
(saved from its opening hours), else Ireland.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Dublin"


def call_timezone(context: Mapping[str, Any] | None) -> ZoneInfo:
    """The business's timezone from the call's variables, else Ireland."""
    name = (context or {}).get("timezone")
    if isinstance(name, str) and name.strip():
        try:
            return ZoneInfo(name.strip())
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo(DEFAULT_TIMEZONE)


def todays_date_line(
    context: Mapping[str, Any] | None = None, now: datetime | None = None
) -> str:
    """E.g. "Today is Friday 6 November 2026 and it's 14:05 (Europe/Dublin)." plus
    how to use it."""
    tz = call_timezone(context)
    local = (now or datetime.now(UTC)).astimezone(tz)
    return (
        f"Today is {local:%A} {local.day} {local:%B %Y} and it's {local:%H:%M} "
        f"({tz.key} time). Work out every date the caller mentions, such as "
        '"this Friday", "tomorrow" or "next week", from today\'s date. '
        "Save dates as YYYY-MM-DD in this year or later, never a date in the past, "
        "and say the weekday with the date when you read it back."
    )

"""Irish/UK wording for report emails: dates, durations, money, and phone
numbers masked because an email is less private than the app. Pure."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from api.services.call_notifications.phone import to_e164
from api.services.email_reports.periods import Frequency, Period

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_label(moment: datetime) -> str:
    """ "Friday 6 November"."""
    return f"{_DAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]}"


def short_day(moment: datetime) -> str:
    """ "6 Nov"."""
    return f"{moment.day} {_MONTHS[moment.month - 1][:3]}"


def clock(moment: datetime) -> str:
    """ "6 pm", "9:30 am", "12 pm"."""
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    if moment.minute:
        return f"{hour}:{moment.minute:02d} {suffix}"
    return f"{hour} {suffix}"


def hour_label(hour: int) -> str:
    """0 -> "12am", 13 -> "1pm" (short, under a bar)."""
    return f"{hour % 12 or 12}{'am' if hour < 12 else 'pm'}"


def period_title(period: Period) -> str:
    """The span in words, as the subject and header say it."""
    start = period.start
    if period.frequency == Frequency.DAILY:
        # Named after the day it is sent: the 24 hours end on that day (the
        # day before, for a midnight send time).
        last = (period.end - timedelta(microseconds=1)).astimezone(start.tzinfo)
        return day_label(last)
    if period.frequency == Frequency.WEEKLY:
        last = period.end - timedelta(days=1)
        if start.month == last.month:
            return f"{start.day}–{last.day} {_MONTHS[start.month - 1]}"
        return f"{short_day(start)} – {short_day(last)}"
    return f"{_MONTHS[start.month - 1]} {start.year}"


def period_subtitle(period: Period) -> str:
    if period.frequency == Frequency.DAILY:
        since = daily_since(period)
        if not period.complete:
            end = period.end.astimezone(period.start.tzinfo)
            return f"{since[0].upper()}{since[1:]}, up to {clock(end)}"
        if since == "since midnight":
            return "The whole day"
        return f"{clock(period.start)} yesterday to {clock(period.start)} today"
    if period.frequency == Frequency.WEEKLY:
        return "Monday to Sunday"
    return "The whole month"


def daily_since(period: Period) -> str:
    """Where a daily report starts, in words: "since 6 pm yesterday", or
    "since midnight" when it is sent at midnight."""
    start = period.start
    if start.hour == 0 and start.minute == 0:
        return "since midnight"
    return f"since {clock(start)} yesterday"


def report_name(frequency: Frequency) -> str:
    return {
        Frequency.DAILY: "daily report",
        Frequency.WEEKLY: "weekly report",
        Frequency.MONTHLY: "monthly report",
    }[frequency]


def compared_with(frequency: Frequency) -> str:
    return {
        Frequency.DAILY: "the same time last week",
        Frequency.WEEKLY: "the week before",
        Frequency.MONTHLY: "the month before",
    }[frequency]


def change_text(change: int | None, frequency: Frequency) -> str | None:
    """ "4 more than the same time last week", or None when too few calls."""
    if change is None:
        return None
    if change == 0:
        return f"Same as {compared_with(frequency)}"
    more = "more" if change > 0 else "fewer"
    return f"{abs(change)} {more} than {compared_with(frequency)}"


def duration_text(seconds: float | None) -> str | None:
    """ "2 min 14 s", "48 s"."""
    if seconds is None:
        return None
    total = round(seconds)
    minutes, secs = divmod(total, 60)
    if minutes and secs:
        return f"{minutes} min {secs} s"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def euro(amount: Decimal | float) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    sign = "-" if value < 0 else ""
    return f"{sign}€{abs(value):,.2f}"


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def mask_phone(raw: str | None) -> str:
    """ "+353872141234" -> "087 214 xxxx"; other countries keep their code:
    "+447700900123" -> "+44 7700 90xxxx". Withheld or unreadable numbers
    say so rather than show part of something."""
    if not raw:
        return "Number withheld"
    e164 = to_e164(raw)
    if e164 is None:
        return "Number withheld"
    if e164.startswith("+353"):
        national = "0" + e164[4:]
        if len(national) == 10 and national.startswith("08"):
            return f"{national[:3]} {national[3:6]} xxxx"
        if national.startswith("01"):
            return f"01 {national[2:-4]} xxxx"
        # Other landlines: a three-digit area code (061, 091, ...).
        return f"{national[:3]} {national[3:-4]} xxxx".replace("  ", " ")
    digits = e164[1:]
    code_len = _country_code_length(digits)
    code, rest = digits[:code_len], digits[code_len:]
    visible = rest[:-4]
    head = f"{visible[:4]} {visible[4:]}".strip()
    return f"+{code} {head}xxxx"


# Two-digit country codes callers here most often have; others are read as
# three digits, which only changes where the space goes.
_TWO_DIGIT_CODES = frozenset(
    {"44", "33", "49", "34", "39", "31", "32", "48", "41", "61"}
)


def _country_code_length(digits: str) -> int:
    if digits[0] in "17":
        return 1
    return 2 if digits[:2] in _TWO_DIGIT_CODES else 3

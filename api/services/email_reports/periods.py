"""Which span of time each emailed report covers, and when it is due.

Pure functions, no I/O. Every boundary is a local wall-clock time in the
workspace's zone, turned into an aware datetime by ``zoneinfo``, so a day that
has 23 or 25 hours (the clocks going forward or back) is still midnight to
midnight.

* Daily: the local day from midnight up to the send time (18:00 by default),
  sent at that time, compared with the same hours a week before.
* Weekly: Monday to Sunday, sent on the Monday after at 08:00, compared with
  the week before.
* Monthly: the calendar month, sent on the 1st of the next month at 08:00,
  compared with the month before.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


DEFAULT_DAILY_SEND_TIME = time(18, 0)
# Weekly and monthly reports arrive at the start of the working day.
WEEKLY_MONTHLY_SEND_TIME = time(8, 0)

# A report that couldn't go at its time (the workers were down) still goes
# this long after; later than that it is skipped rather than arriving stale.
GRACE: dict[Frequency, timedelta] = {
    Frequency.DAILY: timedelta(hours=6),
    Frequency.WEEKLY: timedelta(hours=48),
    Frequency.MONTHLY: timedelta(hours=48),
}


@dataclass(frozen=True, slots=True)
class Period:
    frequency: Frequency
    # Stable id of the span: "2026-11-06", "2026-W45" (ISO week), "2026-10".
    key: str
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    # When this report is (or was) due to be sent.
    send_at: datetime
    # False when the span is still running (a preview or test before the
    # send time): the numbers are "so far".
    complete: bool = True


def _at(day: date, clock: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=tz)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def daily_period(day: date, tz: ZoneInfo, send_time: time) -> Period:
    start = _at(day, time.min, tz)
    end = _at(day, send_time, tz)
    week_before = day - timedelta(days=7)
    return Period(
        frequency=Frequency.DAILY,
        key=day.isoformat(),
        start=start,
        end=end,
        previous_start=_at(week_before, time.min, tz),
        previous_end=_at(week_before, send_time, tz),
        send_at=end,
    )


def weekly_period(monday: date, tz: ZoneInfo) -> Period:
    """The week starting on ``monday`` (a Monday)."""
    next_monday = monday + timedelta(days=7)
    year, week, _ = monday.isocalendar()
    return Period(
        frequency=Frequency.WEEKLY,
        key=f"{year}-W{week:02d}",
        start=_at(monday, time.min, tz),
        end=_at(next_monday, time.min, tz),
        previous_start=_at(monday - timedelta(days=7), time.min, tz),
        previous_end=_at(monday, time.min, tz),
        send_at=_at(next_monday, WEEKLY_MONTHLY_SEND_TIME, tz),
    )


def monthly_period(first: date, tz: ZoneInfo) -> Period:
    """The calendar month starting on ``first`` (a 1st)."""
    following = _add_months(first, 1)
    before = _add_months(first, -1)
    return Period(
        frequency=Frequency.MONTHLY,
        key=f"{first.year}-{first.month:02d}",
        start=_at(first, time.min, tz),
        end=_at(following, time.min, tz),
        previous_start=_at(before, time.min, tz),
        previous_end=_at(first, time.min, tz),
        send_at=_at(following, WEEKLY_MONTHLY_SEND_TIME, tz),
    )


def latest_due(
    frequency: Frequency, now: datetime, tz: ZoneInfo, send_time: time
) -> Period:
    """The most recent report whose send time has passed at ``now``."""
    today = now.astimezone(tz).date()
    if frequency == Frequency.DAILY:
        period = daily_period(today, tz, send_time)
        if period.send_at > now:
            period = daily_period(today - timedelta(days=1), tz, send_time)
        return period
    if frequency == Frequency.WEEKLY:
        this_monday = today - timedelta(days=today.weekday())
        period = weekly_period(this_monday - timedelta(days=7), tz)
        if period.send_at > now:
            period = weekly_period(this_monday - timedelta(days=14), tz)
        return period
    this_month = _month_start(today)
    period = monthly_period(_add_months(this_month, -1), tz)
    if period.send_at > now:
        period = monthly_period(_add_months(this_month, -2), tz)
    return period


def due_to_send(
    frequency: Frequency,
    now: datetime,
    tz: ZoneInfo,
    send_time: time,
    last_sent_key: str | None,
) -> Period | None:
    """The report to send now, or None: nothing new is due, the due one was
    already sent, or it is too late to be worth sending."""
    period = latest_due(frequency, now, tz, send_time)
    if last_sent_key is not None and period.key <= last_sent_key:
        # Keys of one frequency sort in time order ("2026-W09" < "2026-W10").
        return None
    if now - period.send_at > GRACE[frequency]:
        return None
    return period


def preview_period(
    frequency: Frequency, now: datetime, tz: ZoneInfo, send_time: time
) -> Period:
    """What a preview or a test shows: for daily, today so far (or the whole
    report once the send time has passed); for weekly and monthly, the last
    full week or month, as the next email would."""
    if frequency != Frequency.DAILY:
        return latest_due(frequency, now, tz, send_time)
    period = daily_period(now.astimezone(tz).date(), tz, send_time)
    if period.end <= now:
        return period
    span = now - period.start
    return Period(
        frequency=period.frequency,
        key=period.key,
        start=period.start,
        end=now,
        previous_start=period.previous_start,
        previous_end=period.previous_start + span,
        send_at=period.send_at,
        complete=False,
    )


def parse_clock(value: str) -> time:
    """ "18:00" -> time(18, 0); raises ValueError otherwise."""
    hour, minute = value.split(":")
    if len(hour) != 2 or len(minute) != 2:
        raise ValueError("Use HH:MM")
    return time(int(hour), int(minute))

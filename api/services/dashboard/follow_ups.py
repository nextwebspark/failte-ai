"""Follow-ups: calls that need a person. Pure functions over ``CallView``s.

What lands here, all read from the stored call:

* the caller asked to be called back, or left their details for a person;
* the agent tried to pass the call to a person and nobody picked up;
* a caller rang two or more times in a row and never reached anyone;
* the call review found a question the agent couldn't answer;
* the call review found the caller wanted a time that was full (unless a
  booking was made on the call anyway);
* the call review found the caller spoke a language the agent doesn't speak
  ("Spoke Polish"): the agent only offered staff or a call back;
* the call review found an emergency: the caller was sent to 112/999.

Done is stored on the call (``annotations.follow_up``, and for the
call-review kinds ``annotations.follow_up_kinds.<kind>``, so each is done on
its own), so it needs no table of its own. A repeat caller's item sits on their latest unreached call: if they
ring again and still reach nobody, a new item opens.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from statistics import median
from typing import Any

from api.services.call_review.review import (
    caller_language,
    spoke_other_language,
    was_emergency,
)
from api.services.dashboard.calls import (
    UNREACHED_RESULTS,
    CallResult,
    CallView,
    number_key,
)
from api.services.workflow.agent_languages import language_name

# Calls this far back can raise a follow-up.
LOOKBACK = timedelta(days=30)
# "This week" on the side panel.
WEEK = timedelta(days=7)
# A repeat caller rang at least this many times in a row without reaching anyone.
REPEAT_CALLS = 2


class FollowUpKind(StrEnum):
    CALLBACK = "callback"
    TRANSFER_NOT_ANSWERED = "transfer_not_answered"
    REPEAT_CALLER = "repeat_caller"
    UNANSWERED_QUESTION = "unanswered_question"
    TIME_WAS_FULL = "time_was_full"
    OTHER_LANGUAGE = "other_language"
    EMERGENCY = "emergency"


# Kinds raised by the call review, each marked done on its own.
REVIEW_KINDS = frozenset(
    {
        FollowUpKind.UNANSWERED_QUESTION,
        FollowUpKind.TIME_WAS_FULL,
        FollowUpKind.OTHER_LANGUAGE,
        FollowUpKind.EMERGENCY,
    }
)


class FollowUpStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    # Both: the to-do list first, then what was done.
    ALL = "all"


@dataclass(frozen=True, slots=True)
class FollowUp:
    kind: FollowUpKind
    call: CallView
    # Calls in a row that reached nobody, this one included (repeat callers;
    # also set on a transfer nobody answered when the caller kept ringing).
    repeat_count: int | None = None
    first_call_at: datetime | None = None

    @property
    def mark(self) -> Mapping[str, Any] | None:
        if self.kind in REVIEW_KINDS:
            return (self.call.follow_up_marks or {}).get(self.kind.value)
        return self.call.follow_up_mark

    @property
    def done(self) -> bool:
        return self.mark is not None

    @property
    def done_at(self) -> datetime | None:
        mark = self.mark
        if not mark:
            return None
        try:
            return datetime.fromisoformat(str(mark.get("done_at")))
        except ValueError:
            return None

    @property
    def group_key(self) -> str:
        return (
            number_key(self.call.caller_number)
            or number_key(self.call.callback_number)
            or f"call-{self.call.run_id}"
        )


def unanswered_questions(call: CallView) -> list[str]:
    questions = (call.review or {}).get("unanswered_questions")
    if not isinstance(questions, list):
        return []
    return [q.strip() for q in questions if isinstance(q, str) and q.strip()]


def _time_was_full(call: CallView) -> bool:
    return (call.review or {}).get("time_was_full") is True and (
        call.result != CallResult.BOOKING_MADE
    )


def follow_ups(calls: Iterable[CallView]) -> list[FollowUp]:
    """Every follow-up the calls raise, open and done: at most one of the
    callback kinds per call, plus one per call-review kind."""
    calls = sorted(calls, key=lambda c: (c.created_at, c.run_id))
    items: dict[int, FollowUp] = {}
    for call in calls:
        if call.result == CallResult.CALLBACK_REQUESTED:
            items[call.run_id] = FollowUp(FollowUpKind.CALLBACK, call)
        elif call.result == CallResult.TRANSFER_NOT_ANSWERED:
            items[call.run_id] = FollowUp(FollowUpKind.TRANSFER_NOT_ANSWERED, call)

    by_caller: dict[str, list[CallView]] = {}
    for call in calls:
        key = number_key(call.caller_number)
        if key is not None and call.result != CallResult.IN_PROGRESS:
            by_caller.setdefault(key, []).append(call)
    for caller_calls in by_caller.values():
        # The calls since this caller last reached the agent or a person.
        unreached: list[CallView] = []
        for call in reversed(caller_calls):
            if call.result not in UNREACHED_RESULTS:
                break
            unreached.append(call)
        if len(unreached) < REPEAT_CALLS:
            continue
        latest, first = unreached[0], unreached[-1]
        existing = items.get(latest.run_id)
        if existing is not None:
            items[latest.run_id] = replace(
                existing, repeat_count=len(unreached), first_call_at=first.created_at
            )
        else:
            items[latest.run_id] = FollowUp(
                FollowUpKind.REPEAT_CALLER,
                latest,
                repeat_count=len(unreached),
                first_call_at=first.created_at,
            )
    reviewed: list[FollowUp] = []
    for call in calls:
        if call.result == CallResult.IN_PROGRESS:
            continue
        if unanswered_questions(call):
            reviewed.append(FollowUp(FollowUpKind.UNANSWERED_QUESTION, call))
        if _time_was_full(call):
            reviewed.append(FollowUp(FollowUpKind.TIME_WAS_FULL, call))
        if spoke_other_language(call.review):
            reviewed.append(FollowUp(FollowUpKind.OTHER_LANGUAGE, call))
        if was_emergency(call.review):
            reviewed.append(FollowUp(FollowUpKind.EMERGENCY, call))
    return [*items.values(), *reviewed]


@dataclass(frozen=True, slots=True)
class FollowUpFilter:
    """What the Follow-ups controls narrow the list to. Every field is
    optional; an empty filter keeps everything."""

    # The call came in at or after ``start`` and before ``end``.
    start: datetime | None = None
    end: datetime | None = None
    kind: FollowUpKind | None = None
    # The search box, and the calls the database search found for it
    # (name, number, summary, what was said). None: no search.
    text: str | None = None
    found: frozenset[int] | None = None


def _digits(text: str) -> str:
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[2:] if digits.startswith("00") else digits.lstrip("0")


def text_matches(item: FollowUp, text: str) -> bool:
    """The search box over what the follow-up itself shows: the caller's
    name, why they rang, the number they asked to be rung on, and the
    questions the agent couldn't answer. (Name, number, summary and what was
    said on the call are searched in the database: ``FollowUpFilter.found``.)"""
    needle = text.strip().casefold()
    if not needle:
        return True
    call = item.call
    words = [call.caller_name, call.call_reason]
    if item.kind == FollowUpKind.UNANSWERED_QUESTION:
        words.extend(unanswered_questions(call))
    if any(needle in w.casefold() for w in words if w):
        return True
    digits = _digits(text)
    return bool(digits) and any(
        digits in (number_key(n) or "")
        for n in (call.caller_number, call.callback_number)
    )


def matches(item: FollowUp, f: FollowUpFilter, *, kind: bool = True) -> bool:
    """Whether ``item`` passes the filter (``kind=False`` ignores its kind,
    for the kind chips' own counts)."""
    at = item.call.created_at
    if f.start is not None and at < f.start:
        return False
    if f.end is not None and at >= f.end:
        return False
    if kind and f.kind is not None and item.kind != f.kind:
        return False
    if f.text and f.text.strip():
        found = f.found or frozenset()
        if item.call.run_id not in found and not text_matches(item, f.text):
            return False
    return True


def ordered(items: Sequence[FollowUp], status: FollowUpStatus) -> list[FollowUp]:
    """Open items grouped by caller, the caller waiting longest first, each
    caller's items oldest first. Done items newest done first. All: the open
    items, then the done ones, each in that order."""
    if status == FollowUpStatus.ALL:
        return [
            *ordered(items, FollowUpStatus.OPEN),
            *ordered(items, FollowUpStatus.DONE),
        ]
    if status == FollowUpStatus.DONE:
        done = [i for i in items if i.done]
        return sorted(
            done,
            key=lambda i: (
                i.done_at.timestamp() if i.done_at else 0,
                i.call.run_id,
                i.kind.value,
            ),
            reverse=True,
        )
    open_items = [i for i in items if not i.done]
    oldest: dict[str, datetime] = {}
    for item in open_items:
        at = item.call.created_at
        if item.group_key not in oldest or at < oldest[item.group_key]:
            oldest[item.group_key] = at
    return sorted(
        open_items,
        key=lambda i: (
            oldest[i.group_key],
            i.group_key,
            i.call.created_at,
            i.call.run_id,
            i.kind.value,
        ),
    )


def week_summary(items: Sequence[FollowUp], now: datetime) -> dict[str, Any]:
    """This week's follow-ups: raised, sorted, and the usual (median) wait
    between the call and someone marking it done."""
    since = now - WEEK
    raised = [i for i in items if i.call.created_at >= since]
    sorted_items = [i for i in items if i.done_at is not None and i.done_at >= since]
    waits = [
        (i.done_at - i.call.created_at).total_seconds()
        for i in sorted_items
        if i.done_at is not None and i.done_at >= i.call.created_at
    ]
    return {
        "raised": len(raised),
        "sorted": len(sorted_items),
        "median_wait_minutes": round(median(waits) / 60) if waits else None,
    }


def kind_counts(items: Iterable[FollowUp]) -> dict[str, int]:
    counts = {kind.value: 0 for kind in FollowUpKind}
    for item in items:
        counts[item.kind.value] += 1
    return counts


def follow_up_row(item: FollowUp) -> dict[str, Any]:
    call = item.call
    mark = item.mark or {}
    summary = (call.review or {}).get("summary")
    language = caller_language(call.review)
    return {
        "run_id": call.run_id,
        "workflow_id": call.workflow_id,
        "workflow_name": call.workflow_name,
        "kind": item.kind,
        "created_at": call.created_at,
        "caller_number": call.caller_number,
        "caller_name": call.caller_name,
        "callback_number": call.callback_number,
        "call_reason": call.call_reason,
        "duration_seconds": call.duration_seconds,
        "has_recording": call.has_recording,
        "repeat_count": item.repeat_count,
        "first_call_at": item.first_call_at,
        "done_at": item.done_at,
        "done_by": mark.get("done_by") if item.done else None,
        "summary": summary if isinstance(summary, str) and summary else None,
        "questions": unanswered_questions(call)
        if item.kind == FollowUpKind.UNANSWERED_QUESTION
        else [],
        # The language the caller spoke, from the call review ("pl", "Polish").
        "caller_language": language,
        "caller_language_name": language_name(language),
    }


def done_mark(
    *, user_id: int, name: str | None, email: str | None, now: datetime
) -> dict:
    """What is stored on a call marked done."""
    who = (name or "").strip() or (email or "").split("@")[0].strip() or None
    return {"done_at": now.isoformat(), "done_by_user_id": user_id, "done_by": who}

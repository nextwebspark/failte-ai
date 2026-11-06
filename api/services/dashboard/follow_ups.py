"""Follow-ups: calls that need a person. Pure functions over ``CallView``s.

What lands here, all read from the stored call:

* the caller asked to be called back, or left their details for a person;
* the agent tried to pass the call to a person and nobody picked up;
* a caller rang two or more times in a row and never reached anyone.

Done is stored on the call (``annotations.follow_up``), so it needs no table
of its own. A repeat caller's item sits on their latest unreached call: if they
ring again and still reach nobody, a new item opens.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from statistics import median
from typing import Any

from api.services.dashboard.calls import (
    UNREACHED_RESULTS,
    CallResult,
    CallView,
    number_key,
)

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


class FollowUpStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class FollowUp:
    kind: FollowUpKind
    call: CallView
    # Calls in a row that reached nobody, this one included (repeat callers;
    # also set on a transfer nobody answered when the caller kept ringing).
    repeat_count: int | None = None
    first_call_at: datetime | None = None

    @property
    def done(self) -> bool:
        return self.call.follow_up_mark is not None

    @property
    def done_at(self) -> datetime | None:
        mark = self.call.follow_up_mark
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


def follow_ups(calls: Iterable[CallView]) -> list[FollowUp]:
    """Every follow-up the calls raise, open and done, one per call."""
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
    return list(items.values())


def ordered(items: Sequence[FollowUp], status: FollowUpStatus) -> list[FollowUp]:
    """Open items grouped by caller, the caller waiting longest first, each
    caller's items oldest first. Done items newest done first."""
    if status == FollowUpStatus.DONE:
        done = [i for i in items if i.done]
        return sorted(
            done,
            key=lambda i: (i.done_at.timestamp() if i.done_at else 0, i.call.run_id),
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
    mark = call.follow_up_mark or {}
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
    }


def done_mark(
    *, user_id: int, name: str | None, email: str | None, now: datetime
) -> dict:
    """What is stored on a call marked done."""
    who = (name or "").strip() or (email or "").split("@")[0].strip() or None
    return {"done_at": now.isoformat(), "done_by_user_id": user_id, "done_by": who}

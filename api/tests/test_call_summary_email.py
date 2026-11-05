"""The call summary emailed to the business after a receptionist call."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from api.db.call_summary_client import CallSummaryRun
from api.schemas.call_summary_email import CallSummaryEmailConfiguration
from api.services.call_summary.configuration import resolve_call_summary_email
from api.services.call_summary.notifier import (
    CallSummaryNotifier,
    CallSummaryOutcome,
    skip_reason,
)
from api.services.call_summary.summary import (
    BookingAction,
    booking_changes,
    callback_number_of,
    extract_call_summary,
)
from api.services.email.base import EmailDeliveryError, EmailFailure, EmailMessage
from api.services.email.templates import call_summary_message
from api.services.workflow.starter_templates import STARTER_TEMPLATES
from api.tasks import workflow_completion

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
MESSAGE = {
    "extracted_variables": {
        "caller_name": "Mary Byrne",
        "callback_number": "087 123 4567",
        "call_reason": "Wants to move her cleaning",
    }
}


def _call(name: str, call_id: str, arguments: dict[str, Any], result: object):
    return [
        {
            "type": "rtf-function-call-start",
            "payload": {
                "function_name": name,
                "tool_call_id": call_id,
                "arguments": arguments,
            },
        },
        {
            "type": "rtf-function-call-end",
            "payload": {
                "function_name": name,
                "tool_call_id": call_id,
                "result": result if isinstance(result, str) else json.dumps(result),
            },
        },
    ]


BOOKING = _call(
    "mcp__google_calendar__book_appointment",
    "call-1",
    # The slot id is opaque: the time comes from the calendar's result.
    {"slot_id": "opaque-1", "caller_name": "Tom", "caller_phone": "0861112222"},
    {"booked": True, "event_id": "ev1", "starts_at": "2026-10-20T10:00:00+01:00"},
)
CANCELLATION = _call(
    "mcp__google_calendar__cancel_appointment",
    "call-2",
    {"event_id": "ev0"},
    {"cancelled": True, "say": "Cancelled.", "starts_at": "2026-10-21T15:00:00+01:00"},
)

# Recorded shape of the reschedule tool's result (lands with the
# find-booking work): an outcome string, and the new time when moved.


def _reschedule(outcome: str, starts_at: str | None = "2026-10-22T11:30:00+01:00"):
    return _call(
        "mcp__google_calendar__reschedule_appointment",
        "call-3",
        {"event_id": "ev0", "slot_id": "opaque-2"},
        {"outcome": outcome, "event_id": "ev2", "slots": None, "say": "-"}
        | ({"starts_at": starts_at} if starts_at else {}),
    )


def _run(**changes: Any) -> CallSummaryRun:
    run = CallSummaryRun(
        run_id=77,
        workflow_id=5,
        workflow_name="AI Receptionist · Bloom Dental",
        organization_id=11,
        mode="twilio",
        is_completed=True,
        started_at=NOW,
        workflow_configurations={
            "call_summary_email": {
                "enabled": True,
                "recipients": ["owner@bloom.ie", "desk@bloom.ie"],
            }
        },
        gathered_context=MESSAGE,
    )
    return replace(run, **changes)


# --- what the call left ---------------------------------------------------------


def test_a_callback_number_is_a_message():
    summary = extract_call_summary(MESSAGE, [])

    assert summary is not None
    assert summary.caller_name == "Mary Byrne"
    assert summary.callback_number == "087 123 4567"
    assert summary.reason == "Wants to move her cleaning"
    assert summary.booking_changes == ()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("087 123 4567", "087 123 4567"),
        (871234567, "871234567"),
        ("N/A", None),
        ("unknown", None),
        ("12345", None),
        (True, None),
        (None, None),
    ],
)
def test_only_a_real_number_counts_as_a_callback_number(value, expected):
    assert callback_number_of(value) == expected


@pytest.mark.parametrize(
    "gathered",
    [
        {},
        # A question answered: the caller gave a name and a reason, no number.
        {"extracted_variables": {"caller_name": "Mary", "call_reason": "Hours"}},
        {"extracted_variables": {"callback_number": "N/A"}},
        {"extracted_variables": {"callback_number": "unknown"}},
        {"extracted_variables": "not a mapping"},
    ],
)
def test_no_message_and_no_booking_is_nothing_to_report(gathered):
    assert extract_call_summary(gathered, []) is None


def test_confirmed_bookings_and_cancellations_are_reported_in_order():
    changes = booking_changes([*BOOKING, *CANCELLATION])

    assert [c.action for c in changes] == [
        BookingAction.BOOKED,
        BookingAction.CANCELLED,
    ]
    booked, cancelled = changes
    assert booked.starts_at == datetime.fromisoformat("2026-10-20T10:00:00+01:00")
    assert (booked.caller_name, booked.caller_phone) == ("Tom", "0861112222")
    assert cancelled.starts_at == datetime.fromisoformat("2026-10-21T15:00:00+01:00")


@pytest.mark.parametrize(
    ("outcome", "action"),
    [
        ("moved", BookingAction.MOVED),
        ("old_not_cancelled", BookingAction.MOVED_OLD_KEPT),
    ],
)
def test_a_reschedule_that_moved_the_booking_is_reported(outcome, action):
    (change,) = booking_changes(_reschedule(outcome))

    assert change.action is action
    assert change.starts_at == datetime.fromisoformat("2026-10-22T11:30:00+01:00")


@pytest.mark.parametrize(
    "outcome", ["unchanged", "slot_taken", "not_found", "details_edited", ""]
)
def test_a_reschedule_that_changed_nothing_is_not_reported(outcome):
    assert booking_changes(_reschedule(outcome)) == ()


def test_a_flag_that_is_not_a_json_boolean_is_not_a_booking():
    events = _call("mcp__cal__book_appointment", "x", {}, {"booked": 1})

    assert booking_changes(events) == ()


def test_an_older_tools_service_still_gives_the_booking_time():
    # Transitional: book results from before starts_at; the slot id is the
    # ISO start time there.
    events = _call(
        "mcp__cal__book_appointment",
        "x",
        {"slot_id": "2026-10-20T10:00:00+01:00"},
        {"booked": True},
    )

    (change,) = booking_changes(events)
    assert change.starts_at == datetime.fromisoformat("2026-10-20T10:00:00+01:00")


def test_a_result_without_a_start_time_is_still_a_booking():
    events = _call("mcp__cal__book_appointment", "x", {}, {"booked": True})

    (change,) = booking_changes(events)
    assert change.starts_at is None


@pytest.mark.parametrize(
    "events",
    [
        # The slot had gone: nothing changed in the calendar.
        _call("mcp__cal__book_appointment", "x", {}, {"booked": False, "say": "-"}),
        _call("mcp__cal__cancel_appointment", "x", {}, {"cancelled": False}),
        _call("mcp__cal__book_appointment", "x", {}, "Sorry, the MCP tool failed."),
        # Other tools, and a result for a call that never started.
        _call("mcp__cal__check_appointment_availability", "x", {}, {"slots": []}),
        _call("book_appointment", "x", {}, {"booked": True})[1:],
    ],
)
def test_failed_or_unrelated_tool_calls_are_not_booking_changes(events):
    assert booking_changes(events) == ()


def test_a_booking_alone_is_worth_a_summary():
    summary = extract_call_summary({}, BOOKING)

    assert summary is not None
    assert summary.callback_number is None
    # The name the caller booked under stands in for the captured one.
    assert summary.caller_name == "Tom"


def test_the_template_captures_the_fields_the_summary_reads():
    receptionist = next(t for t in STARTER_TEMPLATES if t.name == "AI Receptionist")
    variables = {
        variable["name"]
        for node in receptionist.definition["nodes"]
        for variable in node["data"].get("extraction_variables", [])
    }

    assert {"caller_name", "callback_number", "call_reason"} <= variables


# --- when to send -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"workflow_configurations": {}}, CallSummaryOutcome.TURNED_OFF),
        (
            {"workflow_configurations": {"call_summary_email": {"enabled": False}}},
            CallSummaryOutcome.TURNED_OFF,
        ),
        ({"mode": "smallwebrtc"}, CallSummaryOutcome.NOT_A_PHONE_CALL),
        ({"mode": "textchat"}, CallSummaryOutcome.NOT_A_PHONE_CALL),
        ({"is_completed": False}, CallSummaryOutcome.NOT_COMPLETED),
        ({"mode": "ari"}, None),
        ({}, None),
    ],
)
def test_skip_reason(changes, expected):
    run = _run(**changes)

    assert (
        skip_reason(run, resolve_call_summary_email(run.workflow_configurations))
        == expected
    )


def test_the_setting_needs_an_address_while_on():
    with pytest.raises(ValidationError):
        CallSummaryEmailConfiguration(enabled=True, recipients=[" "])

    setting = CallSummaryEmailConfiguration(
        enabled=True, recipients=["a@bloom.ie", "A@bloom.ie", ""]
    )
    assert setting.recipients == ["a@bloom.ie"]


def test_an_invalid_stored_setting_reads_as_off():
    stored = {"call_summary_email": {"enabled": True, "recipients": ["nope"]}}

    assert resolve_call_summary_email(stored).enabled is False
    assert resolve_call_summary_email(None).enabled is False


# --- the email ----------------------------------------------------------------------


def _email(**changes: Any) -> EmailMessage:
    fields: dict[str, Any] = {
        "to": "owner@bloom.ie",
        "agent_name": "Reception",
        "call_time": "Wed 14 Oct 2026, 10:30 IST",
        "caller_name": "<b>Mary</b>",
        "callback_number": "087 123 4567",
        "reason": None,
        "booking_lines": ["Booked for Tue 20 Oct 2026, 10:00 IST"],
        "run_url": "https://app.example/workflow/5/run/77",
    }
    return call_summary_message(**{**fields, **changes})


def test_the_email_escapes_what_the_caller_said_and_links_only_the_run():
    message = _email()

    assert message.subject == "<b>Mary</b> called Reception"
    assert "&lt;b&gt;Mary&lt;/b&gt;" in message.html
    assert "<b>Mary</b>" not in message.html
    assert "Reason" not in message.text
    assert "- Booked for Tue 20 Oct 2026, 10:00 IST" in message.text
    assert "See the call: https://app.example/workflow/5/run/77" in message.text
    assert "recording" not in (message.text + message.html).lower()


def test_long_names_are_shortened_in_the_subject():
    message = _email(caller_name="M" * 100, agent_name="A" * 100)

    caller, agent = message.subject.split(" called ")
    assert len(caller) == len(agent) == 60
    assert caller.endswith("…")
    # The body keeps the full name.
    assert "M" * 100 in message.text


# --- sending ------------------------------------------------------------------------


class FakeStore:
    def __init__(
        self, run: CallSummaryRun | None, events: list[dict[str, Any]] | None = None
    ) -> None:
        self.run = run
        self.events = events or []
        self.claims: list[int] = []
        self.event_loads = 0

    async def get_call_summary_run(self, run_id: int) -> CallSummaryRun | None:
        return self.run

    async def get_call_summary_events(self, run_id: int) -> list[dict[str, Any]]:
        self.event_loads += 1
        return self.events

    async def claim_call_summary_email(self, run_id: int, claimed_at: datetime) -> bool:
        if run_id in self.claims:
            return False
        self.claims.append(run_id)
        return True


class FakeSender:
    def __init__(
        self,
        *,
        delivers: bool = True,
        failures: int = 0,
        failure: EmailFailure = EmailFailure.TRANSIENT,
        hang: bool = False,
        broken_for: str | None = None,
    ) -> None:
        self._delivers = delivers
        self.failures = failures
        self.failure = failure
        self.hang = hang
        self.broken_for = broken_for
        self.started = asyncio.Event()
        self.sent: list[EmailMessage] = []
        self.attempts = 0

    @property
    def delivers(self) -> bool:
        return self._delivers

    async def send(self, message: EmailMessage) -> None:
        self.attempts += 1
        self.started.set()
        if self.hang:
            await asyncio.Event().wait()
        if message.to == self.broken_for:
            raise RuntimeError("a bug in the transport")
        if self.failures:
            self.failures -= 1
            raise EmailDeliveryError("Resend failed", failure=self.failure)
        self.sent.append(message)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeLimiter:
    def __init__(self, *, allowed: bool = True, hang: bool = False) -> None:
        self.allowed = allowed
        self.hang = hang
        self.calls: list[tuple[str, int, timedelta]] = []

    async def allow(self, key: str, *, limit: int, window: timedelta) -> bool:
        self.calls.append((key, limit, window))
        if self.hang:
            await asyncio.Event().wait()
        return self.allowed


def _notifier(
    store,
    sender,
    *,
    timezone: str | None = "Europe/Dublin",
    limiter: FakeLimiter | None = None,
    send_timeout: float = 45.0,
):
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def timezone_of(organization_id: int) -> str | None:
        return timezone

    notifier = CallSummaryNotifier(
        store=store,
        email_sender=sender,
        clock=FixedClock(),
        timezone_of=timezone_of,
        rate_limiter=limiter or FakeLimiter(),
        daily_limit=200,
        app_url="https://app.example/",
        send_timeout=send_timeout,
        limiter_timeout=0.05,
        sleep=sleep,
    )
    return notifier, sleeps


async def test_sends_one_email_per_recipient_in_the_business_timezone():
    store = FakeStore(_run(), BOOKING)
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.SENT

    assert sorted(m.to for m in sender.sent) == ["desk@bloom.ie", "owner@bloom.ie"]
    message = next(m for m in sender.sent if m.to == "owner@bloom.ie")
    assert message.subject == "Mary Byrne called AI Receptionist · Bloom Dental"
    assert "on Wed 14 Oct 2026, 10:30 IST" in message.text
    assert "Callback number: 087 123 4567" in message.text
    assert "- Booked for Tue 20 Oct 2026, 10:00 IST (Tom, 0861112222)" in message.text
    assert "https://app.example/workflow/5/run/77" in message.text


async def test_each_email_has_its_own_stable_idempotency_key():
    store = FakeStore(_run())
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    await notifier.notify(77)

    keys = {m.idempotency_key for m in sender.sent}
    assert len(keys) == 2
    assert all(k and k.startswith("call-summary-77-") for k in keys)
    assert not any("bloom.ie" in (k or "") for k in keys)


async def test_without_an_organization_timezone_times_keep_their_own_offset():
    store = FakeStore(_run(), CANCELLATION + BOOKING)
    sender = FakeSender()
    notifier, _ = _notifier(store, sender, timezone=None)

    await notifier.notify(77)

    text = sender.sent[0].text
    assert "on Wed 14 Oct 2026, 09:30 UTC" in text
    assert "- Cancelled the appointment for Wed 21 Oct 2026, 15:00 UTC+01:00" in text
    assert "- Booked for Tue 20 Oct 2026, 10:00 UTC+01:00" in text


@pytest.mark.parametrize(
    ("outcome", "starts_at", "line"),
    [
        (
            "moved",
            "2026-10-22T11:30:00+01:00",
            "- Moved the appointment to Thu 22 Oct 2026, 11:30 IST\n",
        ),
        ("moved", None, "- Moved the appointment\n"),
        (
            "old_not_cancelled",
            "2026-10-22T11:30:00+01:00",
            (
                "- Moved the appointment to Thu 22 Oct 2026, 11:30 IST. The old "
                "booking could not be removed: delete it from the calendar.\n"
            ),
        ),
    ],
)
async def test_a_moved_appointment_is_described(outcome, starts_at, line):
    store = FakeStore(_run(), _reschedule(outcome, starts_at))
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    await notifier.notify(77)

    assert line in sender.sent[0].text


async def test_a_second_completion_does_not_send_again():
    store = FakeStore(_run())
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.SENT
    assert await notifier.notify(77) is CallSummaryOutcome.ALREADY_SENT

    assert len(sender.sent) == 2  # two recipients, once each


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        (None, CallSummaryOutcome.RUN_NOT_FOUND),
        (_run(workflow_configurations={}), CallSummaryOutcome.TURNED_OFF),
        (_run(mode="smallwebrtc"), CallSummaryOutcome.NOT_A_PHONE_CALL),
    ],
)
async def test_skipped_runs_never_load_the_call_or_claim_it(run, expected):
    store = FakeStore(run)
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is expected
    assert store.event_loads == 0
    assert store.claims == []
    assert sender.attempts == 0


async def test_a_call_with_nothing_to_report_is_not_claimed():
    store = FakeStore(_run(gathered_context={}))
    notifier, _ = _notifier(store, FakeSender())

    assert await notifier.notify(77) is CallSummaryOutcome.NOTHING_TO_REPORT
    assert store.claims == []


async def test_with_no_email_provider_nothing_is_sent_or_logged():
    store = FakeStore(_run())
    sender = FakeSender(delivers=False)
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.EMAIL_NOT_CONFIGURED
    # The logging sender would write the caller's details to the log.
    assert sender.attempts == 0
    assert store.claims == []


async def test_a_retryable_failure_is_retried_with_backoff():
    store = FakeStore(_run(workflow_configurations=_one_recipient()))
    sender = FakeSender(failures=2)
    notifier, sleeps = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.SENT
    assert sleeps == [2.0, 8.0]
    assert sender.attempts == 3


async def test_a_final_failure_is_not_retried():
    store = FakeStore(_run(workflow_configurations=_one_recipient()))
    sender = FakeSender(failures=10, failure=EmailFailure.FINAL)
    notifier, sleeps = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.FAILED
    assert sender.attempts == 1
    assert sleeps == []
    # Still claimed: a re-run must not email a summary that may have landed.
    assert store.claims == [77]


async def test_a_provider_error_is_retried_once():
    store = FakeStore(_run(workflow_configurations=_one_recipient()))
    sender = FakeSender(failures=10, failure=EmailFailure.PROVIDER_ERROR)
    notifier, sleeps = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.FAILED
    assert sender.attempts == 2
    assert sleeps == [2.0]


async def test_a_broken_send_does_not_lose_the_others():
    store = FakeStore(_run())
    sender = FakeSender(broken_for="desk@bloom.ie")
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.SENT
    assert [m.to for m in sender.sent] == ["owner@bloom.ie"]


async def test_cancelling_the_job_stops_every_send():
    store = FakeStore(_run())
    sender = FakeSender(hang=True)
    notifier, _ = _notifier(store, sender)

    job = asyncio.create_task(notifier.notify(77))
    await sender.started.wait()
    await asyncio.sleep(0)
    job.cancel()

    with pytest.raises(asyncio.CancelledError):
        await job
    # No send outlives the job: only the test's own task is left running.
    others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert not [t for t in others if "_deliver" in repr(t.get_coro())]


async def test_a_hung_daily_limit_check_fails_open():
    store = FakeStore(_run())
    sender = FakeSender()
    notifier, _ = _notifier(store, sender, limiter=FakeLimiter(hang=True))

    assert await notifier.notify(77) is CallSummaryOutcome.SENT


async def test_when_every_attempt_fails_the_outcome_is_failed():
    store = FakeStore(_run(workflow_configurations=_one_recipient()))
    sender = FakeSender(failures=10)
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.FAILED
    assert sender.attempts == 3


async def test_a_hanging_provider_is_cut_off_by_the_send_timeout():
    store = FakeStore(_run())
    sender = FakeSender(hang=True)
    notifier, _ = _notifier(store, sender, send_timeout=0.05)

    assert await notifier.notify(77) is CallSummaryOutcome.FAILED
    # Both recipients were attempted at once, not one after the other.
    assert sender.attempts == 2


async def test_the_daily_limit_stops_sending_after_the_claim():
    store = FakeStore(_run())
    sender = FakeSender()
    limiter = FakeLimiter(allowed=False)
    notifier, _ = _notifier(store, sender, limiter=limiter)

    assert await notifier.notify(77) is CallSummaryOutcome.DAILY_LIMIT_REACHED
    assert sender.attempts == 0
    assert limiter.calls == [("call-summary:11:2026-10-14", 200, timedelta(days=1))]
    # A duplicate completion is answered by the claim and costs no quota.
    assert await notifier.notify(77) is CallSummaryOutcome.ALREADY_SENT
    assert len(limiter.calls) == 1


def _one_recipient() -> dict[str, Any]:
    return {"call_summary_email": {"enabled": True, "recipients": ["o@bloom.ie"]}}


# --- the completion job -----------------------------------------------------------


@pytest.fixture
def completion_steps(monkeypatch):
    """Record the order of the completion job's last steps."""
    calls: list[tuple[str, int]] = []

    async def notify(run_id: int) -> CallSummaryOutcome:
        calls.append(("notify", run_id))
        return CallSummaryOutcome.SENT

    async def mark_done(run_id: int) -> None:
        calls.append(("done", run_id))

    for step in (
        "run_integrations_post_workflow_run",
        "report_completed_workflow_run_platform_usage",
        "sync_external_pbx_call_record",
    ):
        monkeypatch.setattr(workflow_completion, step, AsyncMock())
    notifier = SimpleNamespace(notify=AsyncMock(side_effect=notify))
    monkeypatch.setattr(
        workflow_completion, "get_call_summary_notifier", lambda: notifier
    )
    monkeypatch.setattr(workflow_completion, "mark_post_call_done", mark_done)
    return SimpleNamespace(calls=calls, notifier=notifier)


async def test_the_completion_job_emails_before_marking_the_run_done(completion_steps):
    await workflow_completion.process_workflow_completion(None, 11)

    # Erasure waits for the marker, so the email is never built from a call
    # that is already being erased.
    assert completion_steps.calls == [("notify", 11), ("done", 11)]


async def test_a_failing_summary_never_fails_the_job(completion_steps):
    completion_steps.notifier.notify.side_effect = RuntimeError("DB went away")

    await workflow_completion.process_workflow_completion(None, 11)

    assert completion_steps.calls == [("done", 11)]

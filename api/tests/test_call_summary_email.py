"""The call summary emailed to the business after a receptionist call."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from api.db.call_summary_client import CallSummaryRun
from api.schemas.call_summary_email import (
    CallSummaryEmailConfiguration,
    resolve_call_summary_email,
)
from api.services.call_summary.notifier import (
    CallSummaryNotifier,
    CallSummaryOutcome,
    skip_reason,
)
from api.services.call_summary.summary import (
    BookingAction,
    booking_changes,
    extract_call_summary,
)
from api.services.email.base import EmailDeliveryError, EmailMessage
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
    {
        "slot_id": "2026-10-20T10:00:00+01:00",
        "caller_name": "Tom",
        "caller_phone": "0861112222",
    },
    {"booked": True, "event_id": "ev1", "say": "That is booked in."},
)
CANCELLATION = _call(
    "mcp__google_calendar__cancel_appointment",
    "call-2",
    {"event_id": "ev0"},
    {"cancelled": True, "say": "Your appointment for Tuesday is cancelled."},
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
        realtime_events=[],
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
    "gathered",
    [
        {},
        # A question answered: the caller gave a name and a reason, no number.
        {"extracted_variables": {"caller_name": "Mary", "call_reason": "Hours"}},
        {"extracted_variables": {"callback_number": "   "}},
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
    assert cancelled.confirmation == "Your appointment for Tuesday is cancelled."


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


def test_the_email_escapes_what_the_caller_said_and_links_only_the_run():
    message = call_summary_message(
        to="owner@bloom.ie",
        agent_name="Reception",
        call_time="Wed 14 Oct 2026, 10:30 IST",
        caller_name="<b>Mary</b>",
        callback_number="087 123 4567",
        reason=None,
        booking_lines=["Booked for Tue 20 Oct 2026, 10:00 IST"],
        run_url="https://app.example/workflow/5/run/77",
    )

    assert message.subject == "<b>Mary</b> called Reception"
    assert "&lt;b&gt;Mary&lt;/b&gt;" in message.html
    assert "<b>Mary</b>" not in message.html
    assert "Reason" not in message.text
    assert "- Booked for Tue 20 Oct 2026, 10:00 IST" in message.text
    assert "See the call: https://app.example/workflow/5/run/77" in message.text
    assert "recording" not in (message.text + message.html).lower()


# --- sending ------------------------------------------------------------------------


class FakeStore:
    def __init__(self, run: CallSummaryRun | None) -> None:
        self.run = run
        self.claims: list[int] = []

    async def get_call_summary_run(self, run_id: int) -> CallSummaryRun | None:
        return self.run

    async def claim_call_summary_email(self, run_id: int, claimed_at: datetime) -> bool:
        if run_id in self.claims:
            return False
        self.claims.append(run_id)
        return True


class FakeSender:
    def __init__(self, *, delivers: bool = True, failures: int = 0) -> None:
        self._delivers = delivers
        self.failures = failures
        self.sent: list[EmailMessage] = []
        self.attempts = 0

    @property
    def delivers(self) -> bool:
        return self._delivers

    async def send(self, message: EmailMessage) -> None:
        self.attempts += 1
        if self.failures:
            self.failures -= 1
            raise EmailDeliveryError("Resend rejected the message (HTTP 500)")
        self.sent.append(message)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _notifier(store, sender, *, timezone: str | None = "Europe/Dublin"):
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
        app_url="https://app.example/",
        sleep=sleep,
    )
    return notifier, sleeps


async def test_sends_one_email_per_recipient_in_the_business_timezone():
    store = FakeStore(_run(realtime_events=BOOKING))
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.SENT

    assert [m.to for m in sender.sent] == ["owner@bloom.ie", "desk@bloom.ie"]
    message = sender.sent[0]
    assert message.subject == "Mary Byrne called AI Receptionist · Bloom Dental"
    assert "on Wed 14 Oct 2026, 10:30 IST" in message.text
    assert "Callback number: 087 123 4567" in message.text
    assert "- Booked for Tue 20 Oct 2026, 10:00 IST (Tom, 0861112222)" in message.text
    assert "https://app.example/workflow/5/run/77" in message.text


async def test_without_an_organization_timezone_times_keep_their_own_offset():
    store = FakeStore(_run(realtime_events=CANCELLATION + BOOKING))
    sender = FakeSender()
    notifier, _ = _notifier(store, sender, timezone=None)

    await notifier.notify(77)

    text = sender.sent[0].text
    assert "on Wed 14 Oct 2026, 09:30 UTC" in text
    assert "- Booked for Tue 20 Oct 2026, 10:00 UTC+01:00" in text
    assert '- Cancelled an appointment: "Your appointment for Tuesday' in text


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
        (_run(gathered_context={}), CallSummaryOutcome.NOTHING_TO_REPORT),
        (_run(mode="smallwebrtc"), CallSummaryOutcome.NOT_A_PHONE_CALL),
    ],
)
async def test_skipped_runs_are_never_claimed(run, expected):
    store = FakeStore(run)
    sender = FakeSender()
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is expected
    assert store.claims == []
    assert sender.attempts == 0


async def test_with_no_email_provider_nothing_is_sent_or_logged():
    store = FakeStore(_run())
    sender = FakeSender(delivers=False)
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.EMAIL_NOT_CONFIGURED
    # The logging sender would write the caller's details to the log.
    assert sender.attempts == 0
    assert store.claims == []


async def test_a_failed_send_is_retried_with_backoff():
    store = FakeStore(_run(workflow_configurations=_one_recipient()))
    sender = FakeSender(failures=2)
    notifier, sleeps = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.SENT
    assert sleeps == [2.0, 8.0]
    assert sender.attempts == 3


async def test_when_every_attempt_fails_the_outcome_is_failed():
    store = FakeStore(_run(workflow_configurations=_one_recipient()))
    sender = FakeSender(failures=10)
    notifier, _ = _notifier(store, sender)

    assert await notifier.notify(77) is CallSummaryOutcome.FAILED
    assert sender.attempts == 3
    # Still claimed: a re-run must not email a summary that may have landed.
    assert store.claims == [77]


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

"""After-call notifications: what counts as a booking, a message or a missed
call, the words sent, and the job that sends them. DB-free: the database and
both providers are fakes."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from api.enums import OrgRole
from api.schemas.call_notifications import CallNotificationSettings
from api.services.call_notifications import outcome as outcome_module
from api.services.call_notifications.messages import (
    UNCONFIRMED_BOOKING_NOTE,
    CallFacts,
    booking_confirmation_text,
    business_email,
    spoken_when,
)
from api.services.call_notifications.outcome import (
    CallEvent,
    MissedReason,
    classify_call,
    confirmed_bookings,
    is_phone_call,
)
from api.services.call_notifications.phone import textable_number, to_e164
from api.services.call_notifications.service import (
    EmailDelivery,
    send_call_notifications,
)
from api.services.call_notifications.settings import CONFIG_KEY, email_recipients
from api.services.email.base import EmailDeliveryError, EmailFailure
from api.services.sms.base import SmsDeliveryError

SLOT = "2026-11-14T19:30:00+00:00"


def book_record(
    *,
    booked=True,
    event_id="evt-1",
    slot_id=SLOT,
    party_size=4,
    status="completed",
    name="mcp__google_calendar__book_appointment",
):
    """A tool_results entry as ToolExecutionOwner records an MCP call: the
    result is the MCP server's JSON text."""
    result = {"booked": booked, "say": "That is booked in for 7:30pm."}
    if booked:
        result["event_id"] = event_id
    return {
        "visit_id": "v1",
        "tool_call_id": f"call-{event_id}",
        "function_name": name,
        "arguments": {
            "slot_id": slot_id,
            "caller_name": "Mary Byrne",
            "caller_phone": "0871234567",
            "party_size": party_size,
        },
        "status": status,
        "result": json.dumps(result),
    }


def cancel_record(event_id="evt-1", cancelled=True):
    return {
        "function_name": "mcp__google_calendar__cancel_appointment",
        "arguments": {"event_id": event_id},
        "status": "completed",
        "result": json.dumps({"cancelled": cancelled, "say": "Cancelled."}),
    }


SPOKE = {"call_tags": ["user_speech"], "call_status": "end_call"}


# --- which calls notify ---------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "call_type", "notifies"),
    [
        ("twilio", "inbound", True),
        ("ari", "inbound", True),
        ("telnyx", "inbound", True),
        ("twilio", "outbound", False),
        # Browser test calls and text chats never notify.
        ("webrtc", "inbound", False),
        ("smallwebrtc", "inbound", False),
        ("textchat", "inbound", False),
    ],
)
def test_only_inbound_phone_calls_notify(mode, call_type, notifies):
    assert is_phone_call(mode, call_type) is notifies


# --- bookings -----------------------------------------------------------------------


def test_a_calendar_confirmed_booking_uses_the_tool_call():
    [booking] = confirmed_bookings([book_record()])

    assert booking.event_id == "evt-1"
    assert booking.start == datetime(2026, 11, 14, 19, 30, tzinfo=UTC)
    assert booking.party_size == 4
    assert booking.caller_phone == "0871234567"


def test_the_extracted_fields_never_make_a_booking():
    gathered = {
        **SPOKE,
        "booking_outcome": "booked",
        "booking_date": "2026-11-14",
        "booking_time": "19:30",
        "party_size": "4",
    }
    outcome = classify_call(gathered_context=gathered, logs=None, usage_info=None)

    # Told to the business as a message to check, never as a booking.
    assert outcome.event is CallEvent.MESSAGE_TAKEN
    assert outcome.unconfirmed_booking_claim is True
    assert outcome.bookings == []


@pytest.mark.parametrize(
    "record",
    [
        book_record(booked=False),
        book_record(status="timeout"),
        book_record(status="failed"),
        book_record(slot_id="not a time"),
        book_record(slot_id=""),
        book_record(event_id=""),
        {
            **book_record(),
            "result": "Sorry, the MCP tool returned no content.",
        },
        {**book_record(), "result": "Error executing tool: calendar down"},
        # Another tool that happens to answer booked: true.
        book_record(name="mcp__crm__save_lead"),
    ],
)
def test_anything_short_of_a_confirmation_is_not_a_booking(record):
    assert confirmed_bookings([record]) == []


def test_a_booking_cancelled_on_the_same_call_does_not_count():
    assert confirmed_bookings([book_record(), cancel_record()]) == []
    # A cancel that failed leaves the booking in place.
    assert len(confirmed_bookings([book_record(), cancel_record(cancelled=False)])) == 1


def test_a_moved_booking_keeps_only_the_new_one():
    bookings = confirmed_bookings(
        [
            book_record(event_id="old"),
            cancel_record("old"),
            book_record(event_id="new", slot_id="2026-11-15T13:00:00+00:00"),
        ]
    )
    assert [b.event_id for b in bookings] == ["new"]


def test_a_retried_booking_is_one_booking():
    # The calendar answers a retry of a booking that went through with the
    # same event id.
    assert len(confirmed_bookings([book_record(), book_record()])) == 1


def test_party_size_is_optional():
    [booking] = confirmed_bookings([book_record(party_size=None)])
    assert booking.party_size is None


def test_a_booking_beats_a_message():
    gathered = {
        **SPOKE,
        "caller_name": "Mary",
        "call_reason": "Table",
        "tool_results": [book_record()],
    }
    outcome = classify_call(gathered_context=gathered, logs=None, usage_info=None)
    assert outcome.event is CallEvent.BOOKING_MADE


# --- messages --------------------------------------------------------------------


@pytest.mark.parametrize(
    "gathered",
    [
        {"caller_name": "Mary"},
        {"callback_number": "087 123 4567"},
        {"call_reason": "Wants a quote"},
        {"booking_outcome": "requested"},
        {"booking_outcome": "Requested "},
    ],
)
def test_a_message_is_any_captured_detail_or_a_requested_booking(gathered):
    outcome = classify_call(
        gathered_context={**SPOKE, **gathered}, logs=None, usage_info=None
    )
    assert outcome.event is CallEvent.MESSAGE_TAKEN
    assert outcome.unconfirmed_booking_claim is False


def test_blank_fields_are_not_a_message():
    gathered = {**SPOKE, "caller_name": "  ", "call_reason": None}
    outcome = classify_call(gathered_context=gathered, logs=None, usage_info=None)
    assert outcome.event is None


# --- missed calls -----------------------------------------------------------------


def transfer_log(status):
    # The call log stores str(result): a Python repr.
    result = str({"status": status, "reason": "no_answer", "message": "x"})
    return {
        "realtime_feedback_events": [
            {
                "type": "rtf-function-call-end",
                "payload": {"function_name": "transfer_to_reception", "result": result},
            }
        ]
    }


@pytest.mark.parametrize(
    ("gathered", "logs", "usage", "reason"),
    [
        (
            {"call_status": "no-answer", "call_tags": ["not_connected"]},
            None,
            {"call_duration_seconds": 0},
            MissedReason.NEVER_CONNECTED,
        ),
        # Rejected at call start (workflow_run_failure).
        (
            {"call_status": "error", "call_disposition": "error"},
            None,
            None,
            MissedReason.NEVER_CONNECTED,
        ),
        (
            {"call_status": "pipeline_error", "call_tags": ["user_speech"]},
            None,
            None,
            MissedReason.FAULT,
        ),
        (
            {"call_status": "user_hangup", "call_tags": ["user_hangup"]},
            None,
            {"call_duration_seconds": 40},
            MissedReason.SILENT,
        ),
        (
            {"call_status": "user_idle_max_duration_exceeded", "call_tags": []},
            None,
            None,
            MissedReason.SILENT,
        ),
        (
            {"call_status": "user_hangup", "call_tags": ["user_speech"]},
            None,
            {"call_duration_seconds": 9.5},
            MissedReason.SHORT_HANGUP,
        ),
        (
            {"call_status": "end_call", "call_tags": ["user_speech"]},
            transfer_log("transfer_failed"),
            {"call_duration_seconds": 80},
            MissedReason.TRANSFER_UNANSWERED,
        ),
    ],
)
def test_missed_calls(gathered, logs, usage, reason):
    outcome = classify_call(gathered_context=gathered, logs=logs, usage_info=usage)
    assert outcome.event is CallEvent.MISSED_CALL
    assert outcome.missed_reason is reason


@pytest.mark.parametrize(
    ("gathered", "logs", "usage"),
    [
        # Asked a question, got an answer, said goodbye.
        (
            {"call_status": "end_call", "call_tags": ["user_speech"]},
            None,
            {"call_duration_seconds": 70},
        ),
        # Hung up after a real conversation.
        (
            {"call_status": "user_hangup", "call_tags": ["user_speech"]},
            None,
            {"call_duration_seconds": 45},
        ),
        # A person answered the transfer, even after an earlier failed try.
        (
            {"call_status": "transfer_call", "call_tags": []},
            transfer_log("transfer_failed"),
            {"call_duration_seconds": 20},
        ),
        # A transfer that connected is not a failed one.
        (
            {"call_status": "end_call", "call_tags": ["user_speech"]},
            transfer_log("transfer_success"),
            {"call_duration_seconds": 60},
        ),
    ],
)
def test_helped_callers_are_not_missed(gathered, logs, usage):
    outcome = classify_call(gathered_context=gathered, logs=logs, usage_info=usage)
    assert outcome.event is None


def test_a_message_after_a_failed_transfer_is_a_message():
    gathered = {
        "call_status": "end_call",
        "call_tags": ["user_speech"],
        "caller_name": "Sean",
    }
    outcome = classify_call(
        gathered_context=gathered, logs=transfer_log("transfer_failed"), usage_info=None
    )
    assert outcome.event is CallEvent.MESSAGE_TAKEN


def test_the_call_log_is_never_evaluated_as_code():
    logs = {
        "realtime_feedback_events": [
            {
                "type": "rtf-function-call-end",
                "payload": {"result": "__import__('os').system('echo hi')"},
            },
            {"type": "rtf-function-call-end", "payload": None},
            "garbage",
        ]
    }
    assert outcome_module.transfer_failed(logs) is False


# --- numbers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        ("+353871234567", "+353871234567"),
        ("+353 87 123 4567", "+353871234567"),
        ("087 123 4567", "+353871234567"),
        ("087-123-4567", "+353871234567"),
        ("(01) 555 0100", "+35315550100"),
        ("353871234567", "+353871234567"),
        ("0044 7700 900123", "+447700900123"),
        ("sip:+353871234567@sip.carrier.net", "+353871234567"),
        ("anonymous", None),
        ("", None),
        ("123", None),
        (None, None),
        ("sip:reception@pbx.local", None),
    ],
)
def test_numbers_become_e164_with_ireland_as_home(raw, e164):
    assert to_e164(raw) == e164


def test_texts_go_to_the_first_mobile_number():
    # An Irish landline can't take a text; the booking's mobile is next.
    assert textable_number("+35315550100", "087 123 4567") == "+353871234567"
    assert textable_number("anonymous", None, "0044 7700 900123") == "+447700900123"
    assert textable_number("anonymous", "01 555 0100") is None


# --- what is sent ---------------------------------------------------------------


def test_the_confirmation_text_uses_the_calendar_details():
    [booking] = confirmed_bookings([book_record()])

    text = booking_confirmation_text(
        booking=booking, business_name="Luigi's", business_number="+35315550100"
    )

    assert text == (
        "Luigi's: your booking for Saturday 14 Nov at 7:30pm, table for 4, is "
        "confirmed. To change it call +35315550100."
    )


def test_the_confirmation_text_without_party_size_or_number():
    [booking] = confirmed_bookings(
        [book_record(party_size=None, slot_id="2026-11-16T09:00:00+00:00")]
    )
    text = booking_confirmation_text(
        booking=booking, business_name="Bloom\nDental", business_number=None
    )
    assert text == (
        "Bloom Dental: your booking for Monday 16 Nov at 9am, is confirmed. "
        "To change it, call us."
    )


def test_times_read_in_the_calendar_zone():
    # 19:30 in Dublin summer time, stored with its offset.
    assert spoken_when(datetime.fromisoformat("2026-07-03T19:30:00+01:00")) == (
        "Friday 3 Jul at 7:30pm"
    )
    assert spoken_when(datetime.fromisoformat("2026-07-03T00:05:00")) == (
        "Friday 3 Jul at 12:05am"
    )


def facts(**overrides):
    values = {
        "business_name": "Luigi's",
        "business_number": "+35315550100",
        "caller_number": "+353871234567",
        "called_at": datetime(2026, 11, 6, 18, 2, tzinfo=UTC),
        "call_url": "https://app.example.com/workflow/3/run/42",
        "gathered_context": {},
    }
    return CallFacts(**{**values, **overrides})


def test_the_booking_email():
    outcome = classify_call(
        gathered_context={**SPOKE, "tool_results": [book_record()]},
        logs=None,
        usage_info=None,
    )
    email = business_email(to="owner@example.com", outcome=outcome, facts=facts())

    assert email.to == "owner@example.com"
    assert email.subject == "New booking: Mary Byrne, Saturday 14 Nov at 7:30pm"
    assert "Party size: 4" in email.text
    assert "When: Saturday 14 Nov at 7:30pm" in email.text
    assert "See the call: https://app.example.com/workflow/3/run/42" in email.text
    assert 'href="https://app.example.com/workflow/3/run/42"' in email.html


def test_the_message_email_escapes_what_the_caller_said():
    gathered = {
        **SPOKE,
        "caller_name": "<b>Sean</b>",
        "callback_number": "087 765 4321",
        "call_reason": "Quote\r\nBcc: x@example.com",
    }
    outcome = classify_call(gathered_context=gathered, logs=None, usage_info=None)
    email = business_email(
        to="o@example.com", outcome=outcome, facts=facts(gathered_context=gathered)
    )

    assert email.subject == "Message from <b>Sean</b>"
    assert "\n" not in email.subject
    assert "About: Quote Bcc: x@example.com" in email.text
    assert "Call back on: 087 765 4321" in email.text
    assert "<b>Sean</b>" not in email.html
    assert "&lt;b&gt;Sean&lt;/b&gt;" in email.html
    assert UNCONFIRMED_BOOKING_NOTE not in email.text


def test_an_unconfirmed_booking_is_flagged_in_the_email():
    gathered = {**SPOKE, "booking_outcome": "booked"}
    outcome = classify_call(gathered_context=gathered, logs=None, usage_info=None)
    email = business_email(
        to="o@example.com", outcome=outcome, facts=facts(gathered_context=gathered)
    )
    assert email.subject == "Message from +353871234567"
    assert UNCONFIRMED_BOOKING_NOTE in email.text


def test_the_missed_call_email():
    gathered = {"call_status": "user_hangup", "call_tags": []}
    outcome = classify_call(gathered_context=gathered, logs=None, usage_info=None)
    email = business_email(
        to="o@example.com", outcome=outcome, facts=facts(caller_number=None)
    )
    assert email.subject == "Missed call from a withheld number"
    assert "didn't say anything" in email.text


# --- settings ------------------------------------------------------------------------


def test_extra_recipients_are_checked_and_deduplicated():
    settings = CallNotificationSettings(
        extra_recipients=["a@example.com", "A@example.com", "b@example.com"]
    )
    assert settings.extra_recipients == ["a@example.com", "b@example.com"]
    with pytest.raises(ValidationError):
        CallNotificationSettings(extra_recipients=["not an address"])
    with pytest.raises(ValidationError):
        CallNotificationSettings(
            extra_recipients=[f"p{i}@example.com" for i in range(11)]
        )


def test_recipients_are_the_members_plus_extras_once_each():
    settings = CallNotificationSettings(
        extra_recipients=["Owner@example.com", "x@example.com"]
    )
    assert email_recipients(settings, ["owner@example.com", "admin@example.com"]) == [
        "owner@example.com",
        "admin@example.com",
        "x@example.com",
    ]
    only_extras = settings.model_copy(update={"email_members": False})
    assert email_recipients(only_extras, ["admin@example.com"]) == [
        "Owner@example.com",
        "x@example.com",
    ]


# --- the job ---------------------------------------------------------------------------


class FakeDB:
    def __init__(self, run, settings=None, members=None, organization_name="Luigi's"):
        self.run = run
        self.settings = settings
        self.members = members if members is not None else MEMBERS
        self.organization_name = organization_name
        self.claims: dict[tuple[int, str], dict] = {}

    async def get_workflow_run_by_id(self, run_id):
        return self.run if self.run and self.run.id == run_id else None

    async def get_configuration(self, organization_id, key):
        if key == CONFIG_KEY and self.settings is not None:
            return SimpleNamespace(value=self.settings)
        return None

    async def list_organization_members(self, organization_id):
        return self.members

    async def get_organization_by_id(self, organization_id):
        return SimpleNamespace(name=self.organization_name)

    async def claim_call_notification(self, run_id, channel, event):
        if (run_id, channel) in self.claims:
            return False
        self.claims[(run_id, channel)] = {"event": event, "status": "sending"}
        return True

    async def finish_call_notification(self, run_id, channel, **values):
        self.claims[(run_id, channel)].update(values)


def member(email, role):
    return SimpleNamespace(email=email, role=role)


MEMBERS = [
    member("admin@example.com", OrgRole.ADMIN),
    member("owner@example.com", OrgRole.VIEWER),
    member("dev@example.com", OrgRole.DEVELOPER),
    member("staff@example.com", OrgRole.STAFF),
    member(None, OrgRole.VIEWER),
]


class FakeEmail:
    def __init__(self, fail_for=(), delivers=True):
        self.sent = []
        self.fail_for = set(fail_for)
        self._delivers = delivers

    @property
    def delivers(self):
        return self._delivers

    async def send(self, message):
        if message.to in self.fail_for:
            raise EmailDeliveryError("rejected")
        self.sent.append(message)


class FakeSms:
    def __init__(self, fail=False, delivers=True):
        self.sent = []
        self.fail = fail
        self._delivers = delivers

    @property
    def delivers(self):
        return self._delivers

    async def send(self, message):
        if self.fail:
            raise SmsDeliveryError("Twilio rejected the message (HTTP 400)")
        self.sent.append(message)


def make_run(gathered, *, mode="twilio", call_type="inbound", initial=None):
    return SimpleNamespace(
        id=42,
        workflow_id=3,
        mode=mode,
        call_type=call_type,
        created_at=datetime(2026, 11, 6, 18, 2, tzinfo=UTC),
        initial_context=initial
        if initial is not None
        else {
            "caller_number": "+353871234567",
            "called_number": "+35315550100",
            "business_name": "Luigi's",
        },
        gathered_context=gathered,
        logs={},
        usage_info={"call_duration_seconds": 95},
        workflow=SimpleNamespace(organization_id=7, template_context_variables={}),
    )


BOOKED = {**SPOKE, "tool_results": [book_record()]}


async def no_wait(_seconds):
    return None


# Retries without waiting, no daily cap.
FAST = EmailDelivery(sleep=no_wait)


async def run_job(db, email=None, sms=None, delivery=FAST):
    email = email or FakeEmail()
    sms = sms or FakeSms()
    await send_call_notifications(
        42,
        db=db,
        email_sender_factory=lambda: email,
        sms_sender_factory=lambda: sms,
        delivery=delivery,
    )
    return email, sms


async def test_a_booking_emails_owners_and_admins_and_texts_the_caller():
    db = FakeDB(make_run(BOOKED), settings={"extra_recipients": ["chef@example.com"]})

    email, sms = await run_job(db)

    assert [m.to for m in email.sent] == [
        "admin@example.com",
        "owner@example.com",
        "chef@example.com",
    ]
    assert {m.subject for m in email.sent} == {
        "New booking: Mary Byrne, Saturday 14 Nov at 7:30pm"
    }
    [text] = sms.sent
    assert text.to == "+353871234567"
    assert text.body == (
        "Luigi's: your booking for Saturday 14 Nov at 7:30pm, table for 4, is "
        "confirmed. To change it call +35315550100."
    )
    assert db.claims[(42, "email")]["status"] == "sent"
    assert db.claims[(42, "email")]["recipient_count"] == 3
    assert db.claims[(42, "sms")]["status"] == "sent"


async def test_a_retry_sends_nothing_twice():
    db = FakeDB(make_run(BOOKED))
    await run_job(db)

    email, sms = await run_job(db)

    assert email.sent == []
    assert sms.sent == []


@pytest.mark.parametrize("mode", ["webrtc", "smallwebrtc", "textchat"])
async def test_browser_and_chat_tests_notify_no_one(mode):
    db = FakeDB(make_run(BOOKED, mode=mode))

    email, sms = await run_job(db)

    assert email.sent == [] and sms.sent == [] and db.claims == {}


async def test_a_message_emails_and_texts_no_one():
    db = FakeDB(make_run({**SPOKE, "caller_name": "Sean", "call_reason": "Quote"}))

    email, sms = await run_job(db)

    assert {m.subject for m in email.sent} == {"Message from Sean"}
    assert sms.sent == []
    assert (42, "sms") not in db.claims


async def test_an_unconfirmed_booking_never_texts_the_caller():
    db = FakeDB(
        make_run({**SPOKE, "booking_outcome": "booked", "booking_time": "19:30"})
    )

    email, sms = await run_job(db)

    assert len(email.sent) == 2
    assert sms.sent == []


async def test_switched_off_events_send_nothing():
    db = FakeDB(
        make_run(BOOKED),
        settings={"email_on_booking": False, "text_caller_booking_confirmation": False},
    )

    email, sms = await run_job(db)

    assert email.sent == [] and sms.sent == [] and db.claims == {}


async def test_email_off_still_texts_the_caller():
    db = FakeDB(make_run(BOOKED), settings={"email_enabled": False})

    email, sms = await run_job(db)

    assert email.sent == []
    assert len(sms.sent) == 1


async def test_missed_calls_can_be_switched_off_alone():
    silent = {"call_status": "user_hangup", "call_tags": []}
    db = FakeDB(make_run(silent), settings={"email_on_missed_call": False})
    email, _ = await run_job(db)
    assert email.sent == []

    db = FakeDB(make_run(silent))
    email, _ = await run_job(db)
    assert {m.subject for m in email.sent} == {"Missed call from +353871234567"}


async def test_failures_are_recorded_and_never_raised():
    db = FakeDB(make_run(BOOKED))

    email, _ = await run_job(
        db, email=FakeEmail(fail_for={"admin@example.com"}), sms=FakeSms(fail=True)
    )

    assert [m.to for m in email.sent] == ["owner@example.com"]
    assert db.claims[(42, "email")]["status"] == "partial"
    assert db.claims[(42, "email")]["recipient_count"] == 1
    assert db.claims[(42, "sms")]["status"] == "failed"
    assert "HTTP 400" in db.claims[(42, "sms")]["error"]


async def test_a_misconfigured_text_provider_does_not_stop_the_email():
    db = FakeDB(make_run(BOOKED))
    email = FakeEmail()

    def broken():
        raise ValueError("SMS_FROM required for SMS_PROVIDER=twilio")

    await send_call_notifications(
        42,
        db=db,
        email_sender_factory=lambda: email,
        sms_sender_factory=broken,
        delivery=FAST,
    )

    assert len(email.sent) == 2
    assert (42, "sms") not in db.claims


async def test_without_a_provider_texts_are_logged_not_sent():
    db = FakeDB(make_run(BOOKED))

    await run_job(db, sms=FakeSms(delivers=False))

    assert db.claims[(42, "sms")]["status"] == "logged"


async def test_no_mobile_number_means_no_text():
    run = make_run(
        {**SPOKE, "tool_results": [{**book_record(), "arguments": {"slot_id": SLOT}}]},
        initial={"caller_number": "anonymous", "called_number": "+35315550100"},
    )
    db = FakeDB(run)

    _, sms = await run_job(db)

    assert sms.sent == []
    assert (42, "sms") not in db.claims


async def test_no_recipients_claims_nothing():
    db = FakeDB(
        make_run(BOOKED), members=[member("dev@example.com", OrgRole.DEVELOPER)]
    )

    email, _ = await run_job(db)

    assert email.sent == []
    assert (42, "email") not in db.claims


async def test_the_business_name_falls_back_to_the_workspace():
    run = make_run(BOOKED, initial={"caller_number": "+353871234567"})
    db = FakeDB(run, organization_name="Bloom Dental")

    _, sms = await run_job(db)

    assert sms.sent[0].body.startswith("Bloom Dental: your booking")
    assert sms.sent[0].body.endswith("To change it, call us.")


async def test_an_unreadable_run_is_logged_not_raised():
    db = FakeDB(None)
    db.get_workflow_run_by_id = AsyncMock(side_effect=RuntimeError("db down"))

    email, sms = await run_job(db)

    assert email.sent == [] and sms.sent == []


async def test_stored_errors_hold_no_numbers_or_addresses():
    class QuotingSms(FakeSms):
        async def send(self, message):
            raise SmsDeliveryError(
                f"Twilio rejected the message (HTTP 400): The 'To' number "
                f"{message.to} is not valid"
            )

    class QuotingEmail(FakeEmail):
        async def send(self, message):
            raise EmailDeliveryError(f"Resend rejected {message.to}")

    db = FakeDB(make_run(BOOKED))

    await run_job(db, email=QuotingEmail(), sms=QuotingSms())

    sms_error = db.claims[(42, "sms")]["error"]
    email_error = db.claims[(42, "email")]["error"]
    assert "353871234567" not in sms_error and "[number]" in sms_error
    assert "HTTP 400" in sms_error
    assert "@example.com" not in email_error and "[address]" in email_error
    assert db.claims[(42, "email")]["status"] == "failed"


# --- moves and cancellations (find_appointments / reschedule_appointment) ----------


def reschedule_record(
    old="evt-old", new="evt-new", outcome="moved", starts_at="2026-11-20T13:00:00+00:00"
):
    result = {"outcome": outcome, "say": "Moved."}
    if outcome in ("moved", "old_not_cancelled"):
        result.update(event_id=new, starts_at=starts_at)
    return {
        "function_name": "mcp__google_calendar__reschedule_appointment",
        "arguments": {"event_id": old, "slot_id": "2026-11-20T13:00:00+00:00"},
        "status": "completed",
        "result": json.dumps(result),
    }


def cancel_with_time(event_id, starts_at="2026-11-18T10:00:00+00:00"):
    return {
        **cancel_record(event_id),
        "result": json.dumps(
            {"cancelled": True, "say": "Cancelled.", "starts_at": starts_at}
        ),
    }


def test_the_calendars_start_time_beats_the_slot_id():
    record = book_record()
    record["result"] = json.dumps(
        {"booked": True, "event_id": "evt-1", "starts_at": "2026-11-14T20:00:00+00:00"}
    )
    [booking] = confirmed_bookings([record])
    assert booking.start == datetime(2026, 11, 14, 20, 0, tzinfo=UTC)


def test_moving_an_earlier_booking_is_a_move():
    [booking] = confirmed_bookings([reschedule_record()])

    assert booking.moved is True and booking.event_id == "evt-new"
    assert booking.start == datetime(2026, 11, 20, 13, 0, tzinfo=UTC)


def test_moving_this_calls_booking_keeps_its_details():
    [booking] = confirmed_bookings(
        [book_record(event_id="evt-1"), reschedule_record(old="evt-1")]
    )

    assert booking.moved is False and booking.event_id == "evt-new"
    assert booking.party_size == 4 and booking.caller_name == "Mary Byrne"


@pytest.mark.parametrize(
    "outcome", ["slot_taken", "not_found", "unchanged", "handed_off", "details_edited"]
)
def test_a_refused_move_changes_nothing(outcome):
    assert (
        classify_call(
            gathered_context={
                **SPOKE,
                "tool_results": [reschedule_record(outcome=outcome)],
            },
            logs={},
            usage_info={},
        ).event
        is None
    )


def test_cancelling_an_earlier_booking_is_reported():
    outcome = classify_call(
        gathered_context={**SPOKE, "tool_results": [cancel_with_time("evt-old")]},
        logs={},
        usage_info={},
    )

    assert outcome.event is CallEvent.BOOKING_MADE
    assert outcome.bookings == []
    [gone] = outcome.cancelled
    assert gone.start == datetime(2026, 11, 18, 10, 0, tzinfo=UTC)


def test_a_move_that_kept_the_old_booking_is_flagged():
    outcome = classify_call(
        gathered_context={
            **SPOKE,
            "tool_results": [reschedule_record(outcome="old_not_cancelled")],
        },
        logs={},
        usage_info={},
    )
    assert outcome.old_booking_kept is True and len(outcome.bookings) == 1


def test_the_move_and_cancel_emails():
    moved = classify_call(
        gathered_context={
            **SPOKE,
            "caller_name": "Sean",
            "tool_results": [reschedule_record(outcome="old_not_cancelled")],
        },
        logs={},
        usage_info={},
    )
    message = business_email(
        to="a@example.com", outcome=moved, facts=facts(gathered_context=SPOKE)
    )
    assert message is not None
    assert message.subject.startswith("Booking moved: ")
    assert "Moved to: Friday 20 Nov at 1pm" in message.text
    assert "could not remove the old one" in message.text

    cancelled = classify_call(
        gathered_context={**SPOKE, "tool_results": [cancel_with_time("evt-old")]},
        logs={},
        usage_info={},
    )
    message = business_email(to="a@example.com", outcome=cancelled, facts=facts())
    assert message is not None
    assert message.subject.endswith("Wednesday 18 Nov at 10am")
    assert message.subject.startswith("Booking cancelled: ")
    assert "Cancelled: Wednesday 18 Nov at 10am" in message.text


async def test_a_moved_booking_texts_the_new_time():
    db = FakeDB(make_run({**SPOKE, "tool_results": [reschedule_record()]}))

    email, sms = await run_job(db)

    assert {m.subject for m in email.sent} == {
        "Booking moved: +353871234567, Friday 20 Nov at 1pm"
    }
    [text] = sms.sent
    assert text.body.startswith(
        "Luigi's: your booking is moved to Friday 20 Nov at 1pm."
    )


async def test_a_call_that_only_cancelled_texts_no_one():
    db = FakeDB(make_run({**SPOKE, "tool_results": [cancel_with_time("evt-old")]}))

    email, sms = await run_job(db)

    assert len(email.sent) == 2 and sms.sent == []


# --- outbound calls --------------------------------------------------------------


OUTBOUND_NUMBERS = {
    "caller_number": "+35315550100",  # the business's line
    "called_number": "+353861112222",
    "business_name": "Luigi's",
}


async def test_an_outbound_call_that_moved_a_booking_emails_only():
    run = make_run(
        {**SPOKE, "tool_results": [reschedule_record()]},
        call_type="outbound",
        initial=OUTBOUND_NUMBERS,
    )
    db = FakeDB(run)

    email, sms = await run_job(db)

    assert len(email.sent) == 2
    assert "Number called: +353861112222" in email.sent[0].text
    assert sms.sent == [] and (42, "sms") not in db.claims


async def test_an_unanswered_outbound_call_is_not_a_missed_call():
    run = make_run(
        {"call_status": "no-answer", "call_tags": []},
        call_type="outbound",
        initial=OUTBOUND_NUMBERS,
    )
    db = FakeDB(run)

    email, _ = await run_job(db)

    assert email.sent == [] and db.claims == {}


# --- delivery ----------------------------------------------------------------------


class FlakyEmail(FakeEmail):
    """Fails each message ``failures`` times with ``kind``, then sends."""

    def __init__(self, failures, kind):
        super().__init__()
        self.failures = failures
        self.kind = kind
        self.attempts: dict[str, int] = {}

    async def send(self, message):
        self.attempts[message.to] = self.attempts.get(message.to, 0) + 1
        if self.attempts[message.to] <= self.failures:
            raise EmailDeliveryError("try later", failure=self.kind)
        self.sent.append(message)


async def test_each_email_carries_its_own_idempotency_key():
    db = FakeDB(make_run(BOOKED))

    email, _ = await run_job(db)

    keys = [m.idempotency_key for m in email.sent]
    assert all(k and k.startswith("call-notice-42-email-") for k in keys)
    assert len(set(keys)) == len(keys) == 2
    assert all("@" not in k for k in keys)

    # The same run and address always give the same key.
    again, _ = await run_job(FakeDB(make_run(BOOKED)))
    assert [m.idempotency_key for m in again.sent] == keys


@pytest.mark.parametrize(
    ("kind", "failures", "delivered", "attempts"),
    [
        (EmailFailure.TRANSIENT, 2, True, 3),
        (EmailFailure.TRANSIENT, 3, False, 3),
        (EmailFailure.PROVIDER_ERROR, 1, True, 2),
        (EmailFailure.PROVIDER_ERROR, 2, False, 2),
        (EmailFailure.FINAL, 1, False, 1),
    ],
)
async def test_retries_follow_the_failure_kind(kind, failures, delivered, attempts):
    db = FakeDB(make_run(BOOKED))
    waits: list[float] = []

    async def wait(seconds):
        waits.append(seconds)

    sender = FlakyEmail(failures, kind)
    await run_job(db, email=sender, delivery=EmailDelivery(sleep=wait))

    assert sender.attempts == {
        "admin@example.com": attempts,
        "owner@example.com": attempts,
    }
    assert (len(sender.sent) == 2) is delivered
    assert db.claims[(42, "email")]["status"] == ("sent" if delivered else "failed")
    # Both recipients wait the same steps (concurrently, so interleaved).
    assert sorted(waits) == sorted([2.0, 8.0][: attempts - 1] * 2)


async def test_a_slow_provider_is_cut_off_and_recorded():
    class SlowEmail(FakeEmail):
        async def send(self, message):
            if message.to == "admin@example.com":
                await asyncio.sleep(10)
            self.sent.append(message)

    db = FakeDB(make_run(BOOKED))

    email, _ = await run_job(
        db, email=SlowEmail(), delivery=EmailDelivery(sleep=no_wait, send_timeout=0.05)
    )

    assert [m.to for m in email.sent] == ["owner@example.com"]
    assert db.claims[(42, "email")]["status"] == "partial"
    assert "TimeoutError" in db.claims[(42, "email")]["error"]


class Limiter:
    def __init__(self, allow):
        self.allowed = allow
        self.keys: list[str] = []

    async def allow(self, key, *, limit, window):
        self.keys.append(key)
        return self.allowed


async def test_the_daily_limit_holds_emails_back_after_the_claim():
    limiter = Limiter(allow=False)
    db = FakeDB(make_run(BOOKED))

    email, sms = await run_job(
        db, delivery=EmailDelivery(rate_limiter=limiter, sleep=no_wait)
    )

    assert email.sent == []
    assert db.claims[(42, "email")]["status"] == "limited"
    assert limiter.keys and limiter.keys[0].startswith("call-notifications:7:")
    # The caller's text is not part of the business's email allowance.
    assert len(sms.sent) == 1


async def test_a_retried_job_does_not_count_against_the_limit():
    limiter = Limiter(allow=True)
    db = FakeDB(make_run(BOOKED))
    delivery = EmailDelivery(rate_limiter=limiter, sleep=no_wait)

    await run_job(db, delivery=delivery)
    await run_job(db, delivery=delivery)

    assert len(limiter.keys) == 1

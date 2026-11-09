"""Callers who ring while every line is busy: the plan, the TwiML and Call
Control produced, how the call is recorded, and that it is never billed or
reviewed. Provider requests and webhooks are mocked; nothing is dialled."""

import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from starlette.requests import Request
from twilio.request_validator import RequestValidator

from api.errors.telephony_errors import CALLER_LINES_BUSY, TelephonyError
from api.services.call_concurrency import CallConcurrencyLimitError
from api.services.calls import lines_busy as rules
from api.services.calls.lines_busy import (
    FORWARD,
    LINES_BUSY_PROVIDERS,
    MAX_VOICEMAIL_SECONDS,
    SAY,
    VOICEMAIL,
    LinesBusyAction,
    LinesBusyOutcome,
    LinesBusyPlan,
    plan_lines_busy,
)
from api.services.telephony import lines_busy as service
from api.services.telephony.providers.telnyx import lines_busy as telnyx_flow
from api.services.telephony.providers.telnyx.provider import TelnyxProvider
from api.services.telephony.providers.twilio import lines_busy as twiml
from api.services.telephony.providers.twilio.provider import TwilioProvider
from api.services.telephony.providers.twilio.routes import (
    lines_busy_dial_result,
    lines_busy_recording,
    lines_busy_voicemail_done,
)
from api.utils.transfer_number import DEMO_TRANSFER_NUMBER

ALL = frozenset({SAY, FORWARD, VOICEMAIL})
TEAM = "087 123 4567"
TEAM_E164 = "+353871234567"
CALLED = "+35315551234"
BACKEND = "https://api.example.test"


def _plan(facts=None, *, support=ALL, own=(CALLED,), closed=False):
    return plan_lines_busy(facts or {}, support=support, own_numbers=own, closed=closed)


# --- the plan ------------------------------------------------------------------


def test_default_is_forward_with_a_number_else_voicemail():
    plan = _plan({"transfer_number": TEAM})
    assert plan.action == LinesBusyAction.FORWARD
    assert plan.destination == TEAM_E164
    assert plan.chosen is None
    assert plan.voicemail_fallback is True
    assert _plan({}).action == LinesBusyAction.VOICEMAIL


@pytest.mark.parametrize(
    "facts, closed, reason",
    [
        ({"transfer_number": DEMO_TRANSFER_NUMBER}, False, "demo_number"),
        ({"transfer_number": CALLED}, False, "own_number"),
        ({"transfer_number": "12"}, False, "invalid_number"),
        ({"transfer_number": "sip:desk@pbx.example"}, False, "phone_system"),
        ({"transfer_number": TEAM}, True, "closed"),
        ({"lines_busy_action": "forward"}, False, "no_number"),
    ],
)
def test_forward_guards_fall_back_to_a_voicemail(facts, closed, reason):
    plan = _plan(facts, closed=closed)
    assert plan.action == LinesBusyAction.VOICEMAIL
    assert plan.destination is None
    assert plan.reason == reason


def test_another_of_the_agents_numbers_is_never_dialled():
    plan = _plan({"transfer_number": TEAM}, own=(CALLED, TEAM_E164))
    assert plan.action == LinesBusyAction.VOICEMAIL
    assert plan.reason == "own_number"


def test_owner_choices_are_followed():
    facts = {"transfer_number": TEAM}
    assert (
        _plan({**facts, "lines_busy_action": "voicemail"}).action
        == LinesBusyAction.VOICEMAIL
    )
    busy = _plan({**facts, "lines_busy_action": "busy_message"})
    assert busy.action == LinesBusyAction.BUSY_MESSAGE
    assert busy.chosen == LinesBusyAction.BUSY_MESSAGE
    # An unknown stored value reads as no choice.
    assert _plan({**facts, "lines_busy_action": "x"}).action == LinesBusyAction.FORWARD


def test_providers_without_support_say_the_busy_line():
    plan = _plan({"transfer_number": TEAM}, support=frozenset())
    assert plan.action == LinesBusyAction.BUSY_MESSAGE
    assert plan.reason == "not_supported"
    # Can say but not record: a forward is still impossible, so busy line.
    assert _plan({}, support=frozenset({SAY})).action == LinesBusyAction.BUSY_MESSAGE


def test_supported_providers_match_the_providers_themselves():
    twilio = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    telnyx = TelnyxProvider({"api_key": "k", "connection_id": "c"})
    assert twilio.lines_busy_support() == ALL
    assert telnyx.lines_busy_support() == ALL
    assert LINES_BUSY_PROVIDERS == {"twilio", "telnyx"}


def test_outcome_reading():
    plan = {"lines_busy": {"action": "forward"}}
    assert rules.lines_busy_outcome({}) is None
    assert rules.lines_busy_outcome(plan) == LinesBusyOutcome.NO_MESSAGE
    assert (
        rules.lines_busy_outcome({**plan, "lines_busy_forward": {"result": "answered"}})
        == LinesBusyOutcome.FORWARDED
    )
    assert (
        rules.lines_busy_outcome(
            {**plan, "lines_busy_voicemail": {"seconds": 12, "stored": True}}
        )
        == LinesBusyOutcome.VOICEMAIL
    )
    assert (
        rules.lines_busy_outcome({"lines_busy": {"action": "busy_message"}})
        == LinesBusyOutcome.TOLD_BUSY
    )
    assert rules.forward_record("no-answer", "0")["result"] == "not_answered"
    assert rules.forward_record("completed", "42") == {
        "result": "answered",
        "status": "completed",
        "seconds": 42,
    }


# --- TwiML -----------------------------------------------------------------------


def _xml(content: str):
    return ElementTree.fromstring(content.encode())


def test_forward_twiml_says_the_line_then_dials_the_team():
    root = _xml(twiml.forward_twiml(BACKEND, 77, TEAM_E164))
    say, dial = list(root)
    assert say.tag == "Say" and "putting you through to the team" in say.text
    assert dial.tag == "Dial"
    assert dial.attrib["action"] == (
        f"{BACKEND}/api/v1/telephony/twilio/lines-busy/77/dial-result"
    )
    assert dial.attrib["timeout"] == "20"
    assert "callerId" not in dial.attrib
    assert dial.find("Number").text == TEAM_E164
    # No <Connect>/<Stream>: no AI on this call.
    assert root.find("Connect") is None


def test_voicemail_twiml_records_a_capped_message():
    root = _xml(twiml.voicemail_twiml(BACKEND, 77))
    say, record, redirect = list(root)
    assert "leave your name and number after the tone" in say.text
    assert record.tag == "Record"
    assert record.attrib["maxLength"] == str(MAX_VOICEMAIL_SECONDS)
    assert 60 <= MAX_VOICEMAIL_SECONDS <= 90
    assert record.attrib["playBeep"] == "true"
    assert record.attrib["action"].endswith("/lines-busy/77/voicemail-done")
    assert record.attrib["recordingStatusCallback"].endswith("/lines-busy/77/recording")
    assert redirect.tag == "Redirect" and redirect.text.endswith("?empty=1")
    after = _xml(twiml.voicemail_twiml(BACKEND, 77, after_forward=True))
    assert "nobody from the team could take your call" in after.find("Say").text


def test_busy_twiml_is_todays_line():
    root = _xml(twiml.busy_twiml())
    assert root.find("Say").text == CALLER_LINES_BUSY
    assert root.find("Hangup") is not None


async def test_twilio_provider_answers_each_plan():
    provider = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    data = SimpleNamespace(call_id="CA1")
    forward = await provider.lines_busy_response(
        plan=LinesBusyPlan(LinesBusyAction.FORWARD, None, destination=TEAM_E164),
        workflow_run_id=5,
        normalized_data=data,
        backend_endpoint=BACKEND,
    )
    assert forward.media_type == "application/xml"
    assert b"<Dial" in forward.body
    voicemail = await provider.lines_busy_response(
        plan=LinesBusyPlan(LinesBusyAction.VOICEMAIL, None),
        workflow_run_id=5,
        normalized_data=data,
        backend_endpoint=BACKEND,
    )
    assert b"<Record" in voicemail.body


# --- the shared response: plan, record, provider answer ------------------------


def _normalized(provider="twilio"):
    return SimpleNamespace(
        provider=provider,
        direction="inbound",
        call_id="CA1",
        from_number="+353870000009",
        to_number=CALLED,
        account_id="AC1",
        from_country="IE",
        to_country="IE",
        raw_data={"CallSid": "CA1"},
    )


def _workflow(facts):
    return SimpleNamespace(id=14, user_id=3, template_context_variables=facts)


async def _respond(provider_class, provider, facts, *, now=None):
    created = SimpleNamespace(id=900)
    db = Mock()
    db.list_inbound_numbers_for_workflow = AsyncMock(return_value=[(CALLED, "twilio")])
    db.create_workflow_run = AsyncMock(return_value=created)
    db.update_workflow_run = AsyncMock()
    with (
        patch.object(service, "db_client", db),
        patch(
            "api.utils.common.get_backend_endpoints",
            new=AsyncMock(return_value=(BACKEND, "wss://api.example.test")),
        ),
    ):
        response = await service.lines_busy_response(
            provider_class=provider_class,
            provider_instance=provider,
            workflow=_workflow(facts),
            organization_id=11,
            normalized_data=_normalized(provider_class.PROVIDER_NAME),
            telephony_configuration_id=4,
            phone_number_id=8,
            limit=10,
            now=now or datetime(2026, 11, 7, 19, 30, tzinfo=UTC),
        )
    return response, db


async def test_forwarded_call_is_stored_as_lines_busy_and_dialled():
    provider = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    response, db = await _respond(TwilioProvider, provider, {"transfer_number": TEAM})
    assert b"<Dial" in response.body and TEAM_E164.encode() in response.body
    args, kwargs = db.create_workflow_run.call_args
    assert args[1:] == (14, "twilio")
    assert kwargs["call_type"].value == "inbound"
    assert kwargs["organization_id"] == 11
    assert kwargs["initial_context"]["caller_number"] == "+353870000009"
    gathered = kwargs["gathered_context"]
    assert gathered["mapped_call_disposition"] == "lines_busy"
    assert gathered["lines_busy"]["action"] == "forward"
    assert gathered["lines_busy"]["limit"] == 10
    assert gathered["lines_busy"]["forward_to"] == TEAM_E164
    # Not finished yet (the dial result finishes it); never any call time.
    db.update_workflow_run.assert_not_awaited()
    assert "usage_info" not in kwargs


async def test_closed_business_takes_a_voicemail_instead():
    hours = {
        "timezone": "Europe/Dublin",
        "days": [[{"open": "09:00", "close": "17:00"}]] * 7,
        "transfer_only_when_open": True,
    }
    facts = {"transfer_number": TEAM, "opening_hours_schedule": json.dumps(hours)}
    provider = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    response, db = await _respond(TwilioProvider, provider, facts)
    assert b"<Record" in response.body and b"<Dial" not in response.body
    gathered = db.create_workflow_run.call_args.kwargs["gathered_context"]
    assert gathered["lines_busy"]["reason"] == "closed"
    # Open at any time when the owner switched "Only during opening hours" off.
    hours["transfer_only_when_open"] = False
    facts["opening_hours_schedule"] = json.dumps(hours)
    response, _ = await _respond(TwilioProvider, provider, facts)
    assert b"<Dial" in response.body


async def test_busy_line_only_provider_still_records_the_call():
    provider_class = SimpleNamespace(
        PROVIDER_NAME="plivo",
        generate_validation_error_response=Mock(return_value="busy line"),
    )
    provider = SimpleNamespace()  # no lines_busy_support
    response, db = await _respond(provider_class, provider, {"transfer_number": TEAM})
    assert response == "busy line"
    provider_class.generate_validation_error_response.assert_called_once_with(
        TelephonyError.CONCURRENT_CALL_LIMIT
    )
    gathered = db.create_workflow_run.call_args.kwargs["gathered_context"]
    assert gathered["lines_busy"]["action"] == "busy_message"
    assert gathered["lines_busy"]["reason"] == "not_supported"
    # Nothing more will happen: finished straight away.
    assert db.update_workflow_run.await_args.kwargs["is_completed"] is True


async def test_provider_failure_still_says_the_busy_line():
    provider_class = SimpleNamespace(
        PROVIDER_NAME="telnyx",
        generate_validation_error_response=Mock(return_value="busy line"),
    )
    provider = Mock()
    provider.lines_busy_support = Mock(return_value=ALL)
    provider.lines_busy_response = AsyncMock(side_effect=RuntimeError("refused"))
    response, db = await _respond(provider_class, provider, {})
    assert response == "busy line"
    assert db.update_workflow_run.await_args.kwargs["is_completed"] is True


async def test_inbound_route_sends_turned_away_calls_to_the_fallback():
    from api.routes.telephony import handle_inbound_run

    request = SimpleNamespace(headers={}, url="https://api.example.test/inbound/run")
    provider_class = SimpleNamespace(
        PROVIDER_NAME="twilio", generate_validation_error_response=Mock()
    )
    workflow = _workflow({})
    config = SimpleNamespace(id=4, organization_id=11, name="Twilio", credentials={})
    phone_row = SimpleNamespace(id=8, address=CALLED, inbound_workflow_id=14)
    provider = SimpleNamespace(verify_inbound_signature=AsyncMock(return_value=True))
    fallback = AsyncMock(return_value="fallback twiml")
    create_run = AsyncMock()
    with (
        patch(
            "api.routes.telephony.parse_webhook_request",
            new=AsyncMock(return_value=({}, "")),
        ),
        patch(
            "api.routes.telephony._detect_provider",
            new=AsyncMock(return_value=provider_class),
        ),
        patch(
            "api.routes.telephony.normalize_webhook_data", return_value=_normalized()
        ),
        patch(
            "api.routes.telephony.db_client.find_inbound_route_by_account",
            new=AsyncMock(return_value=(config, phone_row)),
        ),
        patch(
            "api.routes.telephony.organization_accepts_calls",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "api.routes.telephony.db_client.get_workflow",
            new=AsyncMock(return_value=workflow),
        ),
        patch(
            "api.routes.telephony.get_telephony_provider_by_id",
            new=AsyncMock(return_value=provider),
        ),
        patch(
            "api.routes.telephony.call_concurrency.acquire_org_slot",
            new=AsyncMock(
                side_effect=CallConcurrencyLimitError(
                    organization_id=11, source="inbound", wait_time=0, max_concurrent=10
                )
            ),
        ),
        patch("api.routes.telephony.lines_busy_response", new=fallback),
        patch("api.routes.telephony._create_inbound_workflow_run", new=create_run),
    ):
        response = await handle_inbound_run(request)
    assert response == "fallback twiml"
    kwargs = fallback.await_args.kwargs
    assert kwargs["workflow"] is workflow
    assert kwargs["organization_id"] == 11
    assert kwargs["limit"] == 10
    assert kwargs["phone_number_id"] == 8
    create_run.assert_not_awaited()
    provider_class.generate_validation_error_response.assert_not_called()


# --- Twilio callbacks ------------------------------------------------------------


def _twilio_request(path, form, provider, query=None):
    query = query or {}
    body = urlencode(form).encode()
    url = f"https://example.test{path}" + (f"?{urlencode(query)}" if query else "")
    signature = RequestValidator(provider.auth_token).compute_signature(url, form)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("example.test", 443),
            "path": path,
            "query_string": urlencode(query).encode(),
            "headers": [
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"x-twilio-signature", signature.encode()),
            ],
        },
        receive,
    )


def _run(action="forward", fallback=True, **extra):
    return SimpleNamespace(
        id=77,
        workflow_id=14,
        gathered_context={
            "call_id": "CA1",
            "lines_busy": {
                "action": action,
                "forward_to": TEAM_E164,
                "voicemail_fallback": fallback,
            },
            **extra,
        },
        recording_url=None,
    )


def _callback_patches(provider, run):
    db = Mock()
    db.get_workflow_run_by_id = AsyncMock(return_value=run)
    db.update_workflow_run = AsyncMock()
    routes_db = Mock()
    routes_db.get_workflow_by_id = AsyncMock(
        return_value=SimpleNamespace(organization_id=11)
    )
    return db, (
        patch.object(service, "db_client", db),
        patch("api.services.telephony.providers.twilio.routes.db_client", routes_db),
        patch(
            "api.services.telephony.providers.twilio.routes.get_telephony_provider_for_run",
            new=AsyncMock(return_value=provider),
        ),
        patch(
            "api.utils.common.get_backend_endpoints",
            new=AsyncMock(return_value=(BACKEND, "wss://x")),
        ),
    )


async def _call(handler, path, form, run, provider=None, **kwargs):
    provider = provider or TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    db, patches = _callback_patches(provider, run)
    with patches[0], patches[1], patches[2], patches[3]:
        response = await handler(77, _twilio_request(path, form, provider), **kwargs)
    return response, db


async def test_forward_answered_hangs_up_and_finishes():
    path = "/api/v1/telephony/twilio/lines-busy/77/dial-result"
    form = {"CallSid": "CA1", "DialCallStatus": "completed", "DialCallDuration": "95"}
    response, db = await _call(lines_busy_dial_result, path, form, _run())
    assert b"<Hangup/>" in response.body
    kwargs = db.update_workflow_run.await_args.kwargs
    assert kwargs["is_completed"] is True
    assert kwargs["gathered_context"]["lines_busy_forward"] == {
        "result": "answered",
        "status": "completed",
        "seconds": 95,
    }
    assert "usage_info" not in kwargs


async def test_forward_not_answered_takes_a_voicemail():
    path = "/api/v1/telephony/twilio/lines-busy/77/dial-result"
    form = {
        "CallSid": "CA1",
        "DialCallStatus": "no-answer",
        "CallStatus": "in-progress",
    }
    response, db = await _call(lines_busy_dial_result, path, form, _run())
    assert b"<Record" in response.body
    assert b"nobody from the team" in response.body
    kwargs = db.update_workflow_run.await_args.kwargs
    assert kwargs.get("is_completed") in (None, False)
    assert kwargs["gathered_context"]["lines_busy_forward"]["result"] == "not_answered"


async def test_callbacks_need_twilios_signature_and_the_runs_call():
    from fastapi import HTTPException

    provider = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    db, patches = _callback_patches(provider, _run())
    request = _twilio_request(
        "/api/v1/telephony/twilio/lines-busy/77/dial-result",
        {"CallSid": "CA1"},
        TwilioProvider({"account_sid": "AC1", "auth_token": "other"}),
    )
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(HTTPException) as bad_signature:
            await lines_busy_dial_result(77, request)
        with pytest.raises(HTTPException) as other_call:
            await lines_busy_dial_result(
                77,
                _twilio_request(
                    "/api/v1/telephony/twilio/lines-busy/77/dial-result",
                    {"CallSid": "CA999"},
                    provider,
                ),
            )
    assert bad_signature.value.status_code == 401
    assert other_call.value.status_code == 403
    # A run that isn't a turned-away call is never acted on.
    db, patches = _callback_patches(provider, SimpleNamespace(gathered_context={}))
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(HTTPException) as not_busy:
            await lines_busy_dial_result(
                77,
                _twilio_request(
                    "/api/v1/telephony/twilio/lines-busy/77/dial-result",
                    {"CallSid": "CA1"},
                    provider,
                ),
            )
    assert not_busy.value.status_code == 404


async def test_voicemail_done_says_goodbye_and_finishes():
    path = "/api/v1/telephony/twilio/lines-busy/77/voicemail-done"
    form = {"CallSid": "CA1", "RecordingDuration": "14"}
    response, db = await _call(
        lines_busy_voicemail_done, path, form, _run("voicemail"), empty=0
    )
    assert b"call you back soon" in response.body
    assert db.update_workflow_run.await_args.kwargs["is_completed"] is True


async def test_recording_is_kept_as_the_calls_recording():
    provider = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    provider.download_recording = AsyncMock(return_value=b"RIFF....WAVE")
    provider.delete_recording = AsyncMock()
    path = "/api/v1/telephony/twilio/lines-busy/77/recording"
    form = {
        "CallSid": "CA1",
        "RecordingStatus": "completed",
        "RecordingUrl": "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE1",
        "RecordingSid": "RE" + "a" * 32,
        "RecordingDuration": "14",
    }
    run = _run("voicemail")
    upload = AsyncMock()
    with patch(
        "api.services.workflow_run_artifacts.upload_workflow_run_artifacts", new=upload
    ):
        db, patches = _callback_patches(provider, run)
        db.get_workflow_run_by_id = AsyncMock(
            side_effect=[run, SimpleNamespace(recording_url="recordings/77.wav")]
        )
        with patches[0], patches[1], patches[2], patches[3]:
            result = await lines_busy_recording(
                77, _twilio_request(path, form, provider)
            )
    assert result == {"status": "success", "stored": True}
    provider.download_recording.assert_awaited_once_with(form["RecordingUrl"])
    upload.assert_awaited_once_with(77, mixed_audio_wav=b"RIFF....WAVE")
    provider.delete_recording.assert_awaited_once_with(form["RecordingSid"])
    assert db.update_workflow_run.await_args.kwargs["gathered_context"] == {
        "lines_busy_voicemail": {"seconds": 14, "stored": True}
    }


async def test_twilio_recording_download_stays_on_twilio():
    provider = TwilioProvider({"account_sid": "AC1", "auth_token": "t"})
    assert await provider.download_recording("https://evil.example/RE1") is None


# --- Telnyx Call Control ---------------------------------------------------------


def _event(event_type, ccid="v3:caller", state=None, **payload):
    return {
        "data": {
            "event_type": event_type,
            "payload": {
                "call_control_id": ccid,
                **(
                    {"client_state": base64.b64encode(state.encode()).decode()}
                    if state
                    else {}
                ),
                **payload,
            },
        }
    }


def _telnyx_run(action="forward", **extra):
    run = _run(action, **extra)
    run.gathered_context["call_id"] = "v3:caller"
    return run


async def _telnyx(event, run):
    provider = Mock()
    provider.call_command = AsyncMock(return_value=True)
    provider.download_recording = AsyncMock(return_value=b"RIFF")
    provider.delete_recording = AsyncMock()
    db = Mock()
    db.update_workflow_run = AsyncMock()
    db.get_workflow_run_by_id = AsyncMock(
        return_value=SimpleNamespace(recording_url="recordings/77.wav")
    )
    with (
        patch.object(service, "db_client", db),
        patch(
            "api.services.workflow_run_artifacts.upload_workflow_run_artifacts",
            new=AsyncMock(),
        ),
    ):
        done = await telnyx_flow.handle_event(
            provider, run, event, backend_endpoint=BACKEND
        )
    return done, provider, db


async def test_telnyx_answers_without_a_stream():
    provider = TelnyxProvider({"api_key": "k", "connection_id": "c"})
    provider.call_command = AsyncMock(return_value=True)
    result = await provider.lines_busy_response(
        plan=LinesBusyPlan(LinesBusyAction.VOICEMAIL, None),
        workflow_run_id=77,
        normalized_data=SimpleNamespace(call_id="v3:caller"),
        backend_endpoint=BACKEND,
    )
    assert result == {"status": "ok"}
    ccid, action, payload = provider.call_command.await_args.args
    assert (ccid, action) == ("v3:caller", "answer")
    assert payload["webhook_url"].startswith(
        f"{BACKEND}/api/v1/telephony/telnyx/lines-busy/77"
    )
    assert "stream_url" not in payload


async def test_telnyx_forward_speaks_then_transfers():
    done, provider, _ = await _telnyx(_event("call.answered"), _telnyx_run())
    assert done == "speak:forward"
    _, action, payload = provider.call_command.await_args.args
    assert action == "speak" and "putting you through" in payload["payload"]

    done, provider, _ = await _telnyx(
        _event("call.speak.ended", state="forward"), _telnyx_run()
    )
    assert done == "transfer"
    _, action, payload = provider.call_command.await_args.args
    assert action == "transfer"
    assert payload["to"] == TEAM_E164
    assert payload["timeout_secs"] == 20
    assert "from" not in payload


async def test_telnyx_forward_nobody_answered_asks_for_a_voicemail():
    done, provider, db = await _telnyx(
        _event("call.hangup", ccid="v3:team", hangup_cause="timeout"), _telnyx_run()
    )
    assert done == "voicemail_after_forward"
    ccid, action, payload = provider.call_command.await_args.args
    assert (ccid, action) == ("v3:caller", "speak")
    forward = db.update_workflow_run.await_args.kwargs["gathered_context"]
    assert forward["lines_busy_forward"]["result"] == "not_answered"

    done, provider, _ = await _telnyx(
        _event("call.speak.ended", state="voicemail"), _telnyx_run()
    )
    assert done == "record"
    _, action, payload = provider.call_command.await_args.args
    assert action == "record_start"
    assert payload["max_length"] == MAX_VOICEMAIL_SECONDS
    assert payload["play_beep"] is True


async def test_telnyx_bridge_means_the_team_answered():
    done, _, db = await _telnyx(_event("call.bridged"), _telnyx_run())
    assert done == "forward_answered"
    forward = db.update_workflow_run.await_args.kwargs["gathered_context"]
    assert forward["lines_busy_forward"]["result"] == "answered"
    # The team's leg ending after that changes nothing.
    answered = _telnyx_run(lines_busy_forward={"result": "answered"})
    done, provider, _ = await _telnyx(_event("call.hangup", ccid="v3:team"), answered)
    assert done == "ignored"
    provider.call_command.assert_not_awaited()


async def test_telnyx_recording_saved_is_kept_then_goodbye():
    event = _event(
        "call.recording.saved",
        recording_urls={"wav": "https://s3.example/rec.wav"},
        recording_started_at="2026-11-07T19:30:00Z",
        recording_ended_at="2026-11-07T19:30:21Z",
        recording_id="0ccc7b54-4df3-4bca-a65a-3da1ecc777f0",
    )
    done, provider, db = await _telnyx(event, _telnyx_run("voicemail"))
    assert done == "voicemail_stored"
    provider.download_recording.assert_awaited_once_with("https://s3.example/rec.wav")
    assert db.update_workflow_run.await_args.kwargs["gathered_context"] == {
        "lines_busy_voicemail": {"seconds": 21, "stored": True}
    }
    assert provider.call_command.await_args.args[1] == "speak"


async def test_telnyx_busy_line_and_hangup_finish_the_call():
    done, provider, _ = await _telnyx(
        _event("call.speak.ended", state="busy"), _telnyx_run("busy_message")
    )
    assert done == "hangup"
    assert provider.call_command.await_args.args[1] == "hangup"
    done, _, db = await _telnyx(_event("call.hangup"), _telnyx_run("voicemail"))
    assert done == "finished"
    assert db.update_workflow_run.await_args.kwargs["is_completed"] is True


# --- never billed, never reviewed -------------------------------------------------


async def test_turned_away_calls_are_never_billed(monkeypatch):
    from api.services import workflow_run_billing as billing

    monkeypatch.setattr(billing, "BILLING_PROVIDER", "stripe")
    charge = AsyncMock()
    monkeypatch.setattr(billing, "charge_workflow_run", charge)
    run = SimpleNamespace(
        id=77,
        mode="twilio",
        is_completed=True,
        gathered_context={"lines_busy": {"action": "forward"}},
        # Even if a duration were ever written, it is not charged.
        usage_info={"call_duration_seconds": 95},
        workflow=SimpleNamespace(organization_id=11),
    )
    await billing.report_workflow_run_platform_usage(run)
    charge.assert_not_awaited()


def test_turned_away_calls_have_no_billable_time():
    from api.services.billing.charging import billable_seconds

    # The run is created without usage_info, so the sweep's duration filter
    # and the charge both see no call time.
    assert billable_seconds({}) == 0


async def test_turned_away_calls_are_not_reviewed():
    from api.services.call_review import service as review

    run = SimpleNamespace(
        call_type="inbound",
        mode="twilio",
        is_completed=True,
        workflow=SimpleNamespace(),
        annotations={},
        gathered_context={"lines_busy": {"action": "voicemail"}},
        logs={},
        usage_info={},
        purged_at=None,
        extra={},
    )
    db = Mock()
    db.get_workflow_run_with_context = AsyncMock(return_value=(run, 11))
    ask = AsyncMock()
    with (
        patch.object(review, "db_client", db),
        patch.object(review, "is_purged_run", return_value=False),
        patch.object(review, "ask_reviewer", ask),
    ):
        outcome = await review.review_call(77)
    assert outcome == review.ReviewOutcome.LINES_BUSY
    ask.assert_not_awaited()


async def test_asterisk_turned_away_call_is_kept_as_no_message():
    db = Mock()
    db.create_workflow_run = AsyncMock(return_value=SimpleNamespace(id=901))
    db.update_workflow_run = AsyncMock()
    with patch.object(service, "db_client", db):
        run_id = await service.record_hung_up_call(
            workflow=_workflow({"transfer_number": TEAM}),
            organization_id=11,
            provider="ari",
            caller_number="+353870000009",
            called_number="1001",
            call_id="chan-1",
            telephony_configuration_id=4,
            phone_number_id=8,
            limit=10,
        )
    assert run_id == 901
    gathered = db.create_workflow_run.call_args.kwargs["gathered_context"]
    assert gathered["lines_busy"]["reason"] == "hung_up"
    # Nobody heard a busy line: the follow-up says they left no message.
    assert rules.lines_busy_outcome(gathered) == LinesBusyOutcome.NO_MESSAGE
    assert db.update_workflow_run.await_args.kwargs["is_completed"] is True

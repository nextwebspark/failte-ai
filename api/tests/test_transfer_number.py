"""Call transfer: the owner's number is checked and stored as E.164, the
transfer never dials a reserved demo number or the agent's own number, and
the staff phone shows the caller's number where the provider allows it.

Everything is mocked: no call is placed and no provider is contacted."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from api.utils import transfer_number as tn
from api.utils.transfer_number import (
    DEMO_TRANSFER_NUMBER,
    LEGACY_DEMO_TRANSFER_NUMBER,
    check_transfer_number,
    dialable_destination,
    is_demo_number,
    is_sip_destination,
)

# ---------------------------------------------------------------- the check


@pytest.mark.parametrize(
    "typed, value, display, kind",
    [
        ("087 123 4567", "+353871234567", "+353 87 123 4567", "Irish mobile"),
        ("0871234567", "+353871234567", "+353 87 123 4567", "Irish mobile"),
        ("00353 87 123 4567", "+353871234567", "+353 87 123 4567", "Irish mobile"),
        ("(01) 234-5678", "+35312345678", "+353 1 234 5678", "Irish landline"),
        ("+44 7911 123456", "+447911123456", "+44 7911 123456", "UK mobile"),
        ("+1 415 555 0123", "+14155550123", "+1 415-555-0123", "US number"),
    ],
)
def test_a_typed_number_is_saved_as_e164_read_as_irish(typed, value, display, kind):
    check = check_transfer_number(typed)
    assert check.ok, check.error
    assert (check.value, check.display, check.kind) == (value, display, kind)
    assert not check.is_demo and not check.is_sip


@pytest.mark.parametrize(
    "typed, says",
    [
        ("087 123", "too short"),
        ("0871234", "isn't a number that can be called"),
        ("+353 87 123 4567 8901 23", "too many digits"),
        ("call me", "doesn't look like a phone number"),
        ("087 CALL ME", "doesn't look like a phone number"),
        ("+999 123 456 789", "country code"),
        ("1550 123 456", "Premium-rate"),
        (LEGACY_DEMO_TRANSFER_NUMBER, "isn't a number that can be called"),
    ],
)
def test_impossible_numbers_are_refused_in_plain_words(typed, says):
    check = check_transfer_number(typed)
    assert not check.ok
    assert says in check.error


def test_the_agents_own_number_is_refused():
    check = check_transfer_number("01 555 0142", own_numbers=["+35315550142"])
    assert not check.ok
    assert "number callers ring" in check.error
    assert "round in a circle" in check.error
    # Someone else's number is fine.
    assert check_transfer_number("087 123 4567", own_numbers=["+35315550142"]).ok


def test_empty_means_no_transfer():
    check = check_transfer_number("   ")
    assert check.ok and check.value == ""


@pytest.mark.parametrize(
    "destination",
    ["sip:alice@pbx.example.com", "PJSIP/101", "101@pbx", "SIP/trunk/0871234567"],
)
def test_sip_destinations_are_kept_as_typed(destination):
    assert is_sip_destination(destination)
    check = check_transfer_number(destination)
    assert check.ok and check.is_sip and check.value == destination
    assert dialable_destination(destination) == destination


def test_the_demo_number_passes_the_check_but_is_marked():
    assert DEMO_TRANSFER_NUMBER == "+35315550100"
    check = check_transfer_number("01 555 0100")
    assert check.ok and check.is_demo
    assert check.value == DEMO_TRANSFER_NUMBER
    for typed in ("+353 1 555 0100", "015550100", DEMO_TRANSFER_NUMBER):
        assert is_demo_number(typed)
    assert is_demo_number(LEGACY_DEMO_TRANSFER_NUMBER)
    assert not is_demo_number("087 123 4567")
    assert not is_demo_number("sip:+35315550100@pbx")


@pytest.mark.parametrize(
    "stored, dialled",
    [
        # Saved before the check existed: spaces would have been dialled.
        ("087 123 4567", "+353871234567"),
        ("+353 87 123 4567", "+353871234567"),
        # One dial string already: left exactly as it is, as PBX dial
        # plans may expect national numbers or extensions.
        ("+353871234567", "+353871234567"),
        ("0871234567", "0871234567"),
        ("101", "101"),
        ("PJSIP/101", "PJSIP/101"),
        # Not a real number: unchanged, for the provider to refuse as before.
        ("12 34", "12 34"),
    ],
)
def test_the_call_dials_e164_for_numbers_stored_with_spaces(stored, dialled):
    assert dialable_destination(stored) == dialled


def test_without_libphonenumber_a_basic_check_still_runs(monkeypatch):
    monkeypatch.setattr(tn, "phonenumbers", None)
    assert tn.check_transfer_number("087 123 4567").value == "+353871234567"
    assert tn.check_transfer_number("00 44 7911 123456").value == "+447911123456"
    assert not tn.check_transfer_number("12").ok
    assert tn.dialable_destination("087 123 4567") == "+353871234567"
    assert tn.is_demo_number("01 555 0100")


# ---------------------------------------------------- facts and the wizard


def _app():
    from fastapi import FastAPI

    from api.enums import OrgRole
    from api.routes.workflow import router
    from api.services.auth.depends import OrgMembership, get_org_membership, get_user

    user = SimpleNamespace(id=1, selected_organization_id=11, is_superuser=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: user
    app.dependency_overrides[get_org_membership] = lambda: OrgMembership(
        user=user, organization_id=11, role=OrgRole.ADMIN
    )
    return app


def _client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _restaurant():
    from api.services.workflow.starter_templates import STARTER_TEMPLATES

    return next(s for s in STARTER_TEMPLATES if s.name == "Restaurant bookings")


def _duplicate(transfer_number):
    starter = _restaurant()
    template = SimpleNamespace(
        id=5,
        template_name=starter.name,
        template_description=starter.description,
        template_json=starter.definition,
        setup_fields=[f.model_dump() for f in starter.setup_fields],
        call_type="inbound",
        icon="utensils",
        featured=False,
        sample_audio_url=None,
        category="restaurant",
        integrations=starter.integrations,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    created = SimpleNamespace(
        id=42,
        name="Harbour Kitchen",
        status="active",
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        current_definition_id=7,
        template_context_variables={},
        call_disposition_codes=None,
        workflow_configurations={},
    )
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(return_value=template)
        db.create_tool = AsyncMock(return_value=SimpleNamespace(tool_uuid="transfer-1"))
        db.create_workflow = AsyncMock(return_value=created)
        response = _client(_app()).post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 5,
                "workflow_name": "Harbour Kitchen",
                "values": {
                    "business_name": "Harbour Kitchen",
                    "business_description": "Seafood in Galway.",
                    "opening_hours": "Tue-Sun 12-22",
                    "address": "1 Quay St, Galway",
                    "booking_questions": "party_size",
                    "transfer_number": transfer_number,
                },
            },
        )
    return response, db


def test_the_wizard_saves_the_number_as_e164():
    response, db = _duplicate("087 123 4567")
    assert response.status_code == 200, response.text
    facts = db.create_workflow.await_args.kwargs["template_context_variables"]
    assert facts["transfer_number"] == "+353871234567"


def test_the_wizard_refuses_an_impossible_number():
    response, db = _duplicate("0871234")
    assert response.status_code == 422
    assert "can be called" in response.json()["detail"]
    db.create_workflow.assert_not_awaited()


def _facts_workflow(value="+353871234567"):
    definition = {
        "nodes": [
            {
                "id": "global",
                "data": {"prompt": "Transfer: {{initial_context.transfer_number}}"},
            }
        ]
    }
    return SimpleNamespace(
        id=42,
        released_definition=None,
        workflow_definition=definition,
        template_context_variables={"transfer_number": value},
    )


def test_editing_the_number_checks_it_against_the_agents_own_numbers():
    with patch("api.routes.workflow.db_client") as db:
        db.get_workflow = AsyncMock(return_value=_facts_workflow())
        db.list_inbound_numbers_for_workflow = AsyncMock(
            return_value=[("+35315550142", "twilio")]
        )
        db.update_business_facts = AsyncMock(return_value={})
        client = _client(_app())
        refused = client.put(
            "/workflow/42/business-facts",
            json={"facts": {"transfer_number": "01 555 0142"}},
        )
        assert refused.status_code == 422
        assert "number callers ring" in refused.json()["detail"]
        db.update_business_facts.assert_not_awaited()

        saved = client.put(
            "/workflow/42/business-facts",
            json={"facts": {"transfer_number": "087 765 4321"}},
        )
    assert saved.status_code == 200, saved.text
    db.update_business_facts.assert_awaited_once_with(
        42, 11, {"transfer_number": "+353877654321"}
    )


def test_emptying_the_number_still_saves():
    with patch("api.routes.workflow.db_client") as db:
        db.get_workflow = AsyncMock(return_value=_facts_workflow())
        db.list_inbound_numbers_for_workflow = AsyncMock(return_value=[])
        db.update_business_facts = AsyncMock(return_value={})
        response = _client(_app()).put(
            "/workflow/42/business-facts", json={"facts": {"transfer_number": ""}}
        )
    assert response.status_code == 200
    db.update_business_facts.assert_awaited_once_with(42, 11, {"transfer_number": None})


def test_the_live_check_says_how_the_number_is_saved():
    with patch("api.routes.workflow.db_client") as db:
        db.list_inbound_numbers_for_workflow = AsyncMock(
            return_value=[("+35315550142", "twilio")]
        )
        client = _client(_app())
        ok = client.post(
            "/workflow/transfer-number/check", json={"number": "087 123 4567"}
        ).json()
        own = client.post(
            "/workflow/transfer-number/check",
            json={"number": "01 555 0142", "workflow_id": 42},
        ).json()
        demo = client.post(
            "/workflow/transfer-number/check", json={"number": "01 555 0100"}
        ).json()
    assert ok == {
        "ok": True,
        "value": "+353871234567",
        "display": "+353 87 123 4567",
        "kind": "Irish mobile",
        "error": None,
        "is_sip": False,
        "is_demo": False,
    }
    assert own["ok"] is False and "round in a circle" in own["error"]
    assert demo["ok"] is True and demo["is_demo"] is True
    db.list_inbound_numbers_for_workflow.assert_awaited_once_with(42, 11)


@pytest.mark.parametrize(
    "facts, numbers, show, shows",
    [
        ({}, [("+35315550142", "twilio")], True, "caller"),
        ({}, [("+35315550142", "telnyx")], True, "caller"),
        ({"transfer_show_caller_number": "off"}, [("+3531", "twilio")], False, "agent"),
        ({}, [("+35315550142", "plivo")], True, "agent"),
        ({}, [("+35315550142", "twilio"), ("+3532", "ari")], True, "agent"),
        ({}, [], True, "unknown"),
    ],
)
def test_transfer_settings_say_what_the_staff_phone_shows(facts, numbers, show, shows):
    with patch("api.routes.workflow.db_client") as db:
        db.get_workflow = AsyncMock(
            return_value=SimpleNamespace(template_context_variables=facts)
        )
        db.list_inbound_numbers_for_workflow = AsyncMock(return_value=numbers)
        body = _client(_app()).get("/workflow/42/transfer-settings").json()
    assert body["show_caller_number"] is show
    assert body["staff_phone_shows"] == shows


def test_turning_the_caller_number_off_and_on():
    with patch("api.routes.workflow.db_client") as db:
        db.get_workflow = AsyncMock(
            return_value=SimpleNamespace(template_context_variables={})
        )
        db.list_inbound_numbers_for_workflow = AsyncMock(return_value=[])
        db.update_business_facts = AsyncMock(return_value={})
        client = _client(_app())
        client.put("/workflow/42/transfer-settings", json={"show_caller_number": False})
        client.put("/workflow/42/transfer-settings", json={"show_caller_number": True})
    assert [c.args for c in db.update_business_facts.await_args_list] == [
        (42, 11, {"transfer_show_caller_number": "off"}),
        (42, 11, {"transfer_show_caller_number": None}),
    ]


# ------------------------------------------------------------ at call time


def test_the_resolver_dials_e164_for_a_number_stored_with_spaces():
    import asyncio

    from api.services.workflow.tools.transfer_resolver import resolve_transfer_config

    resolved = asyncio.run(
        resolve_transfer_config(
            tool=None,
            config={"destination": "{{initial_context.transfer_number}}"},
            arguments={},
            call_context_vars={"transfer_number": "087 123 4567"},
            gathered_context_vars={},
            organization_id=1,
            workflow_run_id=1,
        )
    )
    assert resolved.destination == "+353871234567"


def test_the_guard_never_lets_a_demo_number_through():
    from api.services.workflow.tools.transfer_guard import transfer_guard_result

    for destination in (
        DEMO_TRANSFER_NUMBER,
        "+353 1 555 0100",
        LEGACY_DEMO_TRANSFER_NUMBER,
    ):
        result = transfer_guard_result(destination, {})
        assert result["action"] == "transfer_failed"
        assert result["reason"] == "demo_number"
        assert "take a message" in result["message"]
    assert transfer_guard_result("+353871234567", {}) is None


def test_the_guard_refuses_the_number_the_caller_rang():
    from api.services.workflow.tools.transfer_guard import transfer_guard_result

    inbound = {"direction": "inbound", "called_number": "+35315550142"}
    assert transfer_guard_result("01 555 0142", inbound)["reason"] == "own_number"
    assert transfer_guard_result("+353871234567", inbound) is None
    assert transfer_guard_result("PJSIP/101", inbound) is None
    outbound = {"direction": "outbound", "called_number": "+35315550142"}
    assert transfer_guard_result("+35315550142", outbound) is None


def _run_with_webhook(raw):
    return SimpleNamespace(logs={"inbound_webhook": {"raw_webhook_data": raw}})


def test_twilio_shows_the_caller_with_the_inbound_call_token():
    from api.services.telephony.providers.twilio.provider import TwilioProvider
    from api.services.workflow.tools.transfer_guard import caller_number_params

    provider = TwilioProvider.__new__(TwilioProvider)
    raw = {"From": "+353861112222", "To": "+35315550142", "CallToken": "tok"}
    inbound = {"direction": "inbound"}
    assert caller_number_params(provider, _run_with_webhook(raw), inbound) == {
        "From": "+353861112222",
        "CallToken": "tok",
    }
    # No token (e.g. an older call), a withheld number, the option off, or
    # an outbound call: the business's number, as before.
    no_token = {k: v for k, v in raw.items() if k != "CallToken"}
    assert caller_number_params(provider, _run_with_webhook(no_token), inbound) is None
    anonymous = {**raw, "From": "anonymous"}
    assert caller_number_params(provider, _run_with_webhook(anonymous), inbound) is None
    off = {**inbound, "transfer_show_caller_number": "off"}
    assert caller_number_params(provider, _run_with_webhook(raw), off) is None
    outbound = {"direction": "outbound"}
    assert caller_number_params(provider, _run_with_webhook(raw), outbound) is None


def test_telnyx_shows_the_caller_with_a_diversion_to_our_number():
    from api.services.telephony.providers.telnyx.provider import TelnyxProvider
    from api.services.workflow.tools.transfer_guard import caller_number_params

    provider = TelnyxProvider.__new__(TelnyxProvider)
    raw = {"data": {"payload": {"from": "+353861112222", "to": "+35315550142"}}}
    assert caller_number_params(
        provider, _run_with_webhook(raw), {"direction": "inbound"}
    ) == {"from": "+353861112222", "diversion": "+35315550142"}


@pytest.mark.parametrize(
    "module, cls",
    [
        ("api.services.telephony.providers.plivo.provider", "PlivoProvider"),
        ("api.services.telephony.providers.cloudonix.provider", "CloudonixProvider"),
        ("api.services.telephony.providers.ari.provider", "ARIProvider"),
    ],
)
def test_other_providers_keep_the_business_number(module, cls):
    import importlib

    from api.services.workflow.tools.transfer_guard import caller_number_params

    provider_cls = getattr(importlib.import_module(module), cls)
    provider = provider_cls.__new__(provider_cls)
    raw = {"From": "+353861112222", "CallToken": "tok", "to": "+3531"}
    assert (
        caller_number_params(provider, _run_with_webhook(raw), {"direction": "inbound"})
        is None
    )


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def text(self):
        import json

        return json.dumps(self._body)

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, sent, response):
        self.sent = sent
        self.response = response

    def post(self, endpoint, **kwargs):
        self.sent.append(kwargs)
        return self.response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_twilio_transfer_request_carries_the_caller_number():
    import asyncio

    from api.services.telephony.providers.twilio import provider as twilio

    provider = twilio.TwilioProvider(
        {
            "account_sid": "AC1",
            "auth_token": "t",
            "from_numbers": ["+35315550142"],
        }
    )
    sent = []
    response = _FakeResponse(201, {"sid": "CA2", "status": "queued"})
    with (
        patch.object(
            twilio.aiohttp,
            "ClientSession",
            lambda *a, **k: _FakeSession(sent, response),
        ),
        patch.object(
            twilio, "get_backend_endpoints", AsyncMock(return_value=("https://b", "w"))
        ),
    ):
        result = asyncio.run(
            provider.transfer_call(
                destination="+353871234567",
                transfer_id="t1",
                conference_name="c1",
                From="+353861112222",
                CallToken="tok",
            )
        )
    data = sent[0]["data"]
    assert data["From"] == "+353861112222" and data["CallToken"] == "tok"
    assert data["To"] == "+353871234567"
    assert result["from_number"] == "+353861112222"


def test_telnyx_transfer_request_carries_the_caller_number():
    import asyncio

    from api.services.telephony.providers.telnyx import provider as telnyx

    provider = telnyx.TelnyxProvider(
        {
            "api_key": "k",
            "connection_id": "conn",
            "from_numbers": ["+35315550142"],
        }
    )
    sent = []
    response = _FakeResponse(200, {"data": {"call_control_id": "cc2"}})
    with (
        patch.object(
            telnyx.aiohttp,
            "ClientSession",
            lambda *a, **k: _FakeSession(sent, response),
        ),
        patch.object(
            telnyx, "get_backend_endpoints", AsyncMock(return_value=("https://b", "w"))
        ),
    ):
        result = asyncio.run(
            provider.transfer_call(
                destination="+353871234567",
                transfer_id="t1",
                conference_name="c1",
                **{"from": "+353861112222", "diversion": "+35315550142"},
            )
        )
    payload = sent[0]["json"]
    assert payload["from"] == "+353861112222"
    assert payload["diversion"] == "+35315550142"
    assert result["from_number"] == "+353861112222"


# ------------------------------------------------- the transfer tool itself


def _transfer_handler(call_context_vars):
    from api.services.workflow.pipecat_engine_custom_tools import CustomToolManager
    from api.tests.pipecat_test_utils import stub_agent_runtime

    engine = Mock()
    engine.active_agent = stub_agent_runtime()
    engine._workflow_run_id = 1
    engine._call_context_vars = call_context_vars
    engine._gathered_context = {}
    engine._fetch_recording_audio = None
    engine._audio_config = SimpleNamespace(transport_out_sample_rate=8000)
    engine._transport_output = SimpleNamespace(queue_frame=AsyncMock())
    engine._get_organization_id = AsyncMock(return_value=1)
    engine.set_mute_pipeline = Mock()
    engine.end_call_with_reason = AsyncMock()
    engine.queue_speech = AsyncMock(return_value=None)
    manager = CustomToolManager(engine)
    tool = SimpleNamespace(
        tool_uuid="transfer-tool-uuid",
        name="Put through",
        description="Transfer the caller",
        category="transfer_call",
        definition={
            "schema_version": 1,
            "type": "transfer_call",
            "config": {
                "destination": "{{initial_context.transfer_number}}",
                "timeout": 30,
            },
        },
    )
    handler, _ = manager._create_handler(tool, "transfer_call")
    return handler


async def _run_transfer(handler, provider, workflow_run):
    from api.services.workflow import pipecat_engine_custom_tools as tools

    results = []

    async def result_callback(result, properties=None):
        results.append(result)

    params = Mock(arguments={}, result_callback=result_callback)
    transfer_event = Mock()
    transfer_event.to_result_dict.return_value = {
        "status": "failed",
        "action": "transfer_failed",
        "reason": "no-answer",
    }
    transfer_manager = Mock(
        store_transfer_context=AsyncMock(),
        remove_transfer_context=AsyncMock(),
        wait_for_transfer_completion=AsyncMock(return_value=transfer_event),
    )
    with (
        patch.object(
            tools.db_client,
            "get_workflow_run_by_id",
            AsyncMock(return_value=workflow_run),
        ),
        patch.object(
            tools, "get_telephony_provider_for_run", AsyncMock(return_value=provider)
        ),
        patch.object(
            tools, "get_call_transfer_manager", AsyncMock(return_value=transfer_manager)
        ),
        patch.object(tools, "play_audio_loop", AsyncMock(return_value=None)),
    ):
        await handler(params)
    return results, transfer_manager


def _workflow_run(raw=None):
    from api.enums import WorkflowRunMode

    return SimpleNamespace(
        mode=WorkflowRunMode.TWILIO.value,
        initial_context={},
        gathered_context={"call_id": "CA1"},
        logs={"inbound_webhook": {"raw_webhook_data": raw or {}}},
    )


def _provider():
    provider = Mock()
    provider.supports_transfers.return_value = True
    provider.validate_config.return_value = True
    provider.transfer_call = AsyncMock(return_value={"call_sid": "CA2"})
    provider.transfer_external_pbx_call = AsyncMock()
    provider.transfer_caller_number_params = Mock(return_value=None)
    return provider


@pytest.mark.asyncio
async def test_a_demo_number_is_never_dialled():
    provider = _provider()
    handler = _transfer_handler({"transfer_number": "01 555 0100"})
    results, _ = await _run_transfer(handler, provider, _workflow_run())
    provider.transfer_call.assert_not_awaited()
    provider.transfer_external_pbx_call.assert_not_awaited()
    assert results[-1]["status"] == "transfer_failed"
    assert results[-1]["reason"] == "demo_number"


@pytest.mark.asyncio
async def test_the_transfer_shows_the_caller_and_falls_back_if_refused():
    provider = _provider()
    provider.transfer_caller_number_params = Mock(
        return_value={"From": "+353861112222", "CallToken": "tok"}
    )
    provider.transfer_call = AsyncMock(
        side_effect=[Exception("21210 caller ID refused"), {"call_sid": "CA2"}]
    )
    handler = _transfer_handler(
        {"transfer_number": "087 123 4567", "direction": "inbound"}
    )
    results, transfer_manager = await _run_transfer(
        handler, provider, _workflow_run({"From": "+353861112222", "CallToken": "tok"})
    )
    first, second = provider.transfer_call.await_args_list
    assert first.kwargs["destination"] == "+353871234567"
    assert first.kwargs["From"] == "+353861112222"
    assert first.kwargs["CallToken"] == "tok"
    assert "From" not in second.kwargs and "CallToken" not in second.kwargs
    # The transfer context is stored again for the retry (ARI drops it on
    # failure) and the call goes on to wait for the staff phone.
    assert transfer_manager.store_transfer_context.await_count >= 3
    assert results[-1]["reason"] == "no-answer"


@pytest.mark.asyncio
async def test_with_the_option_off_the_staff_phone_shows_the_business_number():
    provider = _provider()
    provider.transfer_caller_number_params = Mock(
        return_value={"From": "+353861112222", "CallToken": "tok"}
    )
    handler = _transfer_handler(
        {
            "transfer_number": "+353871234567",
            "direction": "inbound",
            "transfer_show_caller_number": "off",
        }
    )
    await _run_transfer(handler, provider, _workflow_run({"CallToken": "tok"}))
    kwargs = provider.transfer_call.await_args.kwargs
    assert "From" not in kwargs and "CallToken" not in kwargs

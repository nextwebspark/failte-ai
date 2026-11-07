"""How callers reach an agent: the stored choice, the first-call check and the
routes. Database calls are stubbed; no call is placed and nothing is bought."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api import constants
from api.routes import organization as organization_routes
from api.routes import phone_setup as routes
from api.schemas.phone_setup import PhoneSetupUpdateRequest
from api.services.telephony.phone_setup import (
    PHONE_SETUP_KEY,
    find_first_call,
    forwarded_from,
    with_setup,
)

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)


def _number(**overrides):
    values = dict(
        id=10,
        telephony_configuration_id=3,
        address="+35315550142",
        address_normalized="+35315550142",
        label=None,
        is_active=True,
        inbound_workflow_id=7,
        extra_metadata={},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _run(raw=None):
    return SimpleNamespace(
        id=501,
        created_at=LATER,
        logs={"inbound_webhook": {"raw_webhook_data": raw or {}}},
    )


# ------------------------------------------------------------------- choice


def test_choosing_a_setup_stamps_when_it_started():
    meta = with_setup(
        {"other": 1}, method="keep_existing", forward_when="no_answer", now=NOW
    )
    assert meta["other"] == 1
    assert meta[PHONE_SETUP_KEY] == {
        "method": "keep_existing",
        "forward_when": "no_answer",
        "started_at": NOW.isoformat(),
    }


def test_saving_the_same_choice_keeps_the_start_and_a_change_restarts_it():
    first = with_setup({}, method="mobile", forward_when="busy", now=NOW)
    same = with_setup(first, method="mobile", forward_when="busy", now=LATER)
    assert same[PHONE_SETUP_KEY]["started_at"] == NOW.isoformat()
    changed = with_setup(first, method="mobile", forward_when="all", now=LATER)
    assert changed[PHONE_SETUP_KEY]["started_at"] == LATER.isoformat()


def test_a_new_number_has_no_forwarding_rule():
    meta = with_setup({}, method="new_number", forward_when="busy", now=NOW)
    assert "forward_when" not in meta[PHONE_SETUP_KEY]


# ---------------------------------------------------------------- the check


def test_forwarded_from_is_read_from_twilios_webhook_when_present():
    assert forwarded_from(_run({"ForwardedFrom": "+35315550100"})) == "+35315550100"
    assert forwarded_from(_run({"ForwardedFrom": ""})) is None
    assert forwarded_from(_run({})) is None
    assert forwarded_from(SimpleNamespace(logs=None)) is None


@pytest.mark.asyncio
async def test_first_call_is_looked_up_from_the_setup_time():
    number = _number(
        extra_metadata=with_setup(
            {}, method="keep_existing", forward_when="all", now=NOW
        )
    )
    db = SimpleNamespace(
        find_first_inbound_run_to_number=AsyncMock(
            return_value=_run({"ForwardedFrom": "+35315550100"})
        )
    )
    first = await find_first_call(
        workflow_id=7, organization_id=4, number=number, db=db
    )
    db.find_first_inbound_run_to_number.assert_awaited_once_with(
        7, 4, "+35315550142", NOW
    )
    assert (first.run_id, first.at, first.forwarded_from) == (
        501,
        LATER,
        "+35315550100",
    )


@pytest.mark.asyncio
async def test_no_setup_means_nothing_to_check():
    db = SimpleNamespace(find_first_inbound_run_to_number=AsyncMock())
    assert (
        await find_first_call(workflow_id=7, organization_id=4, number=_number(), db=db)
        is None
    )
    db.find_first_inbound_run_to_number.assert_not_awaited()


# ------------------------------------------------------------------- routes

USER = SimpleNamespace(selected_organization_id=4)


def _routes_db(numbers, run=None):
    return SimpleNamespace(
        get_workflow=AsyncMock(return_value=SimpleNamespace(id=7)),
        list_phone_numbers_for_workflow=AsyncMock(
            return_value=[(n, "LightMove numbers", "twilio", False) for n in numbers]
        ),
        find_first_inbound_run_to_number=AsyncMock(return_value=run),
        get_phone_number_for_org=AsyncMock(
            return_value=numbers[0] if numbers else None
        ),
        update_phone_number=AsyncMock(),
    )


@pytest.fixture
def switched_off(monkeypatch):
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_AUTH_TOKEN", "")


@pytest.mark.asyncio
async def test_status_reports_waiting_then_received(switched_off):
    meta = with_setup(
        {"lightmove_number": {"provider": "twilio"}},
        method="new_number",
        forward_when=None,
        now=NOW,
    )
    number = _number(extra_metadata=meta)
    db = _routes_db([number])
    with patch.object(routes, "db_client", db):
        waiting = await routes.get_phone_setup(7, USER)
        db.find_first_inbound_run_to_number.return_value = _run()
        received = await routes.get_phone_setup(7, USER)

    assert waiting.platform_numbers_available is False
    [item] = waiting.numbers
    assert item.lightmove_number is True
    assert item.setup.method == "new_number"
    assert item.check.status == "waiting"
    assert received.numbers[0].check.status == "received"
    assert received.numbers[0].check.first_call_run_id == 501
    assert received.numbers[0].check.forwarded_from is None


@pytest.mark.asyncio
async def test_status_without_a_choice_is_not_started(switched_off):
    db = _routes_db([_number()])
    with patch.object(routes, "db_client", db):
        response = await routes.get_phone_setup(7, USER)
    assert response.numbers[0].check.status == "not_started"
    assert response.numbers[0].lightmove_number is False
    db.find_first_inbound_run_to_number.assert_not_awaited()


@pytest.mark.asyncio
async def test_saving_a_forwarding_choice_needs_a_when(switched_off):
    db = _routes_db([_number()])
    with patch.object(routes, "db_client", db):
        with pytest.raises(HTTPException) as raised:
            await routes.update_phone_setup(
                7,
                PhoneSetupUpdateRequest(phone_number_id=10, method="keep_existing"),
                USER,
            )
        assert raised.value.status_code == 400

        await routes.update_phone_setup(
            7,
            PhoneSetupUpdateRequest(
                phone_number_id=10, method="keep_existing", forward_when="no_answer"
            ),
            USER,
        )
    saved = db.update_phone_number.await_args.kwargs
    assert saved["phone_number_id"] == 10
    assert saved["extra_metadata"][PHONE_SETUP_KEY]["forward_when"] == "no_answer"


@pytest.mark.asyncio
async def test_only_this_agents_numbers_can_be_set_up(switched_off):
    db = _routes_db([_number(inbound_workflow_id=8)])
    with patch.object(routes, "db_client", db):
        with pytest.raises(HTTPException) as raised:
            await routes.update_phone_setup(
                7,
                PhoneSetupUpdateRequest(phone_number_id=10, method="new_number"),
                USER,
            )
    assert raised.value.status_code == 404
    db.update_phone_number.assert_not_awaited()


@pytest.mark.asyncio
async def test_lightmove_numbers_answer_503_when_switched_off(switched_off):
    with pytest.raises(HTTPException) as raised:
        await routes.list_available_platform_numbers("local", USER)
    assert raised.value.status_code == 503
    assert "Ask us" in raised.value.detail

    db = _routes_db([])
    with patch.object(routes, "db_client", db):
        with pytest.raises(HTTPException) as raised:
            await routes.get_platform_number(
                7,
                routes.PlatformNumberPurchaseRequest(phone_number="+35315550142"),
                USER,
            )
    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_a_lightmove_number_cannot_be_deleted_from_the_telephony_page():
    number = _number(extra_metadata={"lightmove_number": {"provider_number_id": "PN1"}})
    db = SimpleNamespace(
        get_telephony_configuration_for_org=AsyncMock(
            return_value=SimpleNamespace(id=3, organization_id=4)
        ),
        get_phone_number_for_config=AsyncMock(return_value=number),
        delete_phone_number=AsyncMock(),
    )
    with (
        patch.object(organization_routes, "db_client", db),
        patch.object(organization_routes, "_ensure_config_belongs_to_org", AsyncMock()),
    ):
        with pytest.raises(HTTPException) as raised:
            await organization_routes.delete_phone_number(3, 10, USER)
    assert raised.value.status_code == 409
    db.delete_phone_number.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_managed_line_cannot_be_edited_or_deleted():
    managed = SimpleNamespace(
        id=3,
        provider="twilio",
        credentials={"account_sid": "ACplatform", "managed_by": "lightmove"},
    )
    db = SimpleNamespace(
        get_telephony_configuration_for_org=AsyncMock(return_value=managed),
        delete_telephony_configuration=AsyncMock(),
    )
    with patch.object(organization_routes, "db_client", db):
        with pytest.raises(HTTPException) as raised:
            await organization_routes.delete_telephony_configuration(3, USER)
    assert raised.value.status_code == 409
    db.delete_telephony_configuration.assert_not_awaited()

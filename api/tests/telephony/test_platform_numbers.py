"""LightMove-provided numbers: the Twilio client, the purchase flow and the
credential hook. Every HTTP call is stubbed; nothing reaches Twilio."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api import constants
from api.db.telephony_configuration_client import TelephonyConfigurationConflictError
from api.services.telephony import factory
from api.services.telephony.platform_numbers import (
    PLATFORM_NUMBER_METADATA_KEY,
    PlatformNumberProviderError,
    PlatformNumbersNotConfiguredError,
    apply_platform_credentials,
    get_platform_number_provider,
    is_platform_number,
    service,
)
from api.services.telephony.platform_numbers.twilio import TwilioPlatformNumbers


class _Response:
    def __init__(self, status: int, data=None):
        self.status = status
        self._data = data

    async def json(self, content_type=None):
        return self._data

    async def text(self):
        return str(self._data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def _next(self, method, url, kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def delete(self, url, **kwargs):
        return self._next("DELETE", url, kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _twilio(session, **kwargs):
    return TwilioPlatformNumbers(
        "ACplatform", "secret-token", session_factory=lambda: session, **kwargs
    )


@pytest.fixture
def platform_env(monkeypatch):
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_ACCOUNT_SID", "ACplatform")
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_BUNDLE_SID", "")
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_ADDRESS_SID", "")
    monkeypatch.setattr(constants, "PLATFORM_NUMBERS_COUNTRY", "IE")


@pytest.fixture
def no_platform_env(monkeypatch):
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(constants, "PLATFORM_TWILIO_AUTH_TOKEN", "")


# ---------------------------------------------------------------- Twilio client


@pytest.mark.asyncio
async def test_search_asks_twilio_for_voice_numbers_of_the_kind():
    session = _Session(
        [
            _Response(
                200,
                {
                    "available_phone_numbers": [
                        {
                            "phone_number": "+35315550142",
                            "friendly_name": "01 555 0142",
                            "locality": "Dublin",
                            "address_requirements": "local",
                            "capabilities": {"voice": True, "SMS": False},
                        },
                        {
                            "phone_number": "+35315550143",
                            "capabilities": {"voice": False},
                        },
                    ]
                },
            )
        ]
    )
    found = await _twilio(session).search(country="IE", kind="local", limit=5)

    method, url, kwargs = session.requests[0]
    assert method == "GET"
    assert url.endswith("/Accounts/ACplatform/AvailablePhoneNumbers/IE/Local.json")
    assert kwargs["params"] == {"VoiceEnabled": "true", "PageSize": "5"}
    assert kwargs["auth"].login == "ACplatform"
    assert [n.phone_number for n in found] == ["+35315550142"]
    assert found[0].locality == "Dublin"
    assert found[0].address_requirements == "local"


@pytest.mark.asyncio
async def test_search_mobile_uses_the_mobile_resource_and_404_means_none():
    session = _Session([_Response(404, {"code": 20404, "message": "Not found"})])
    assert await _twilio(session).search(country="IE", kind="mobile") == []
    assert session.requests[0][1].endswith("/AvailablePhoneNumbers/IE/Mobile.json")


@pytest.mark.asyncio
async def test_search_failure_is_a_friendly_error_with_the_detail_kept():
    session = _Session([_Response(401, {"code": 20003, "message": "Authenticate"})])
    with pytest.raises(PlatformNumberProviderError) as raised:
        await _twilio(session).search(country="IE", kind="local")
    assert "try again" in str(raised.value)
    assert raised.value.detail == "20003: Authenticate"
    assert "secret-token" not in raised.value.detail


@pytest.mark.asyncio
async def test_buy_sets_the_inbound_webhook_and_regulatory_sids():
    session = _Session(
        [_Response(201, {"sid": "PN123", "phone_number": "+35315550142"})]
    )
    platform = _twilio(session, bundle_sid="BU1", address_sid="AD1")
    bought = await platform.buy(
        "+35315550142",
        voice_url="https://api.example/api/v1/telephony/inbound/run",
        friendly_name="LightMove org 4 agent 7",
    )

    method, url, kwargs = session.requests[0]
    assert (method, url.rsplit("/", 1)[-1]) == ("POST", "IncomingPhoneNumbers.json")
    assert kwargs["data"] == {
        "PhoneNumber": "+35315550142",
        "VoiceUrl": "https://api.example/api/v1/telephony/inbound/run",
        "VoiceMethod": "POST",
        "FriendlyName": "LightMove org 4 agent 7",
        "BundleSid": "BU1",
        "AddressSid": "AD1",
    }
    assert (bought.phone_number, bought.provider_number_id) == ("+35315550142", "PN123")


@pytest.mark.asyncio
async def test_buy_refused_by_twilio_raises():
    session = _Session([_Response(400, {"code": 21422, "message": "not available"})])
    with pytest.raises(PlatformNumberProviderError) as raised:
        await _twilio(session).buy("+35315550142", voice_url="u", friendly_name="f")
    assert raised.value.detail == "21422: not available"


@pytest.mark.asyncio
async def test_release_deletes_the_incoming_number():
    session = _Session([_Response(204)])
    await _twilio(session).release("PN123")
    method, url, _ = session.requests[0]
    assert method == "DELETE"
    assert url.endswith("/IncomingPhoneNumbers/PN123.json")


def test_the_token_never_shows_in_repr_or_stored_credentials():
    platform = _twilio(_Session([]))
    assert "secret-token" not in repr(platform)
    assert platform.configuration_credentials() == {
        "account_sid": "ACplatform",
        "managed_by": "lightmove",
    }


# --------------------------------------------------------------- configuration


def test_switched_off_without_both_settings(no_platform_env):
    assert get_platform_number_provider() is None


def test_switched_on_with_both_settings(platform_env):
    platform = get_platform_number_provider()
    assert platform is not None and platform.account_id == "ACplatform"


def test_secret_is_added_only_to_managed_rows_for_the_platform_account(platform_env):
    managed = {
        "provider": "twilio",
        "account_sid": "ACplatform",
        "managed_by": "lightmove",
    }
    assert apply_platform_credentials("twilio", managed)["auth_token"] == "secret-token"

    # A customer's own Twilio account is left alone.
    own = {"provider": "twilio", "account_sid": "ACplatform", "auth_token": "theirs"}
    assert apply_platform_credentials("twilio", own) == own
    # A managed row from another (rotated) platform account fails closed.
    stale = {**managed, "account_sid": "ACold"}
    assert "auth_token" not in apply_platform_credentials("twilio", stale)
    assert "auth_token" not in apply_platform_credentials("plivo", managed)


def test_no_secret_when_switched_off(no_platform_env):
    managed = {"account_sid": "ACplatform", "managed_by": "lightmove"}
    assert "auth_token" not in apply_platform_credentials("twilio", managed)


@pytest.mark.asyncio
async def test_factory_loads_the_managed_row_with_the_platform_secret(platform_env):
    row = SimpleNamespace(
        id=3,
        provider="twilio",
        credentials={"account_sid": "ACplatform", "managed_by": "lightmove"},
    )
    db = SimpleNamespace(
        list_active_normalized_addresses_for_config=AsyncMock(
            return_value=["+35315550142"]
        ),
        get_default_caller_id=AsyncMock(return_value=None),
    )
    with patch.object(factory, "db_client", db):
        config = await factory._normalize_with_phone_numbers(row)
    assert config["auth_token"] == "secret-token"
    assert config["account_sid"] == "ACplatform"
    # The stored row was not changed.
    assert "auth_token" not in row.credentials


# -------------------------------------------------------------- purchase flow


class _FakePlatform:
    name = "twilio"
    account_id = "ACplatform"

    def __init__(self):
        self.buy = AsyncMock(
            return_value=SimpleNamespace(
                phone_number="+35315550142", provider_number_id="PN123"
            )
        )
        self.release = AsyncMock()
        self.search = AsyncMock(return_value=[])

    def configuration_credentials(self):
        return {"account_sid": self.account_id, "managed_by": "lightmove"}


def _db(existing_configs=(), create_phone=None):
    config = SimpleNamespace(
        id=11, credentials={"account_sid": "ACplatform", "managed_by": "lightmove"}
    )
    return SimpleNamespace(
        list_telephony_configurations_by_provider=AsyncMock(
            return_value=list(existing_configs)
        ),
        create_telephony_configuration=AsyncMock(return_value=config),
        find_inbound_routing_conflicts=AsyncMock(return_value=[]),
        create_phone_number=create_phone
        or AsyncMock(return_value=SimpleNamespace(id=99)),
    )


@pytest.fixture
def backend():
    with patch.object(
        service,
        "get_backend_endpoints",
        AsyncMock(return_value=("https://api.example", "wss://api.example")),
    ):
        yield


@pytest.mark.asyncio
async def test_buying_creates_a_managed_line_and_records_ownership(
    platform_env, backend
):
    platform = _FakePlatform()
    db = _db()
    with patch.object(service, "assert_no_inbound_routing_conflict", AsyncMock()):
        row = await service.buy_platform_number(
            organization_id=4,
            workflow_id=7,
            phone_number="+353 1 555 0142",
            platform=platform,
            db=db,
        )
    assert row.id == 99

    created = db.create_telephony_configuration.await_args.kwargs
    assert created["provider"] == "twilio"
    assert created["is_default_outbound"] is False
    assert created["credentials"] == {
        "account_sid": "ACplatform",
        "managed_by": "lightmove",
    }

    platform.buy.assert_awaited_once()
    assert platform.buy.await_args.args == ("+35315550142",)
    assert (
        platform.buy.await_args.kwargs["voice_url"]
        == "https://api.example/api/v1/telephony/inbound/run"
    )

    phone = db.create_phone_number.await_args.kwargs
    assert phone["telephony_configuration_id"] == 11
    assert phone["inbound_workflow_id"] == 7
    ownership = phone["extra_metadata"][PLATFORM_NUMBER_METADATA_KEY]
    assert ownership["provider_number_id"] == "PN123"
    assert ownership["billing"] == "not_billed"
    assert phone["extra_metadata"]["phone_setup"]["method"] == "new_number"
    assert is_platform_number(phone["extra_metadata"])


@pytest.mark.asyncio
async def test_existing_managed_line_is_reused(platform_env, backend):
    existing = SimpleNamespace(
        id=5, credentials={"account_sid": "ACplatform", "managed_by": "lightmove"}
    )
    own = SimpleNamespace(id=6, credentials={"account_sid": "ACtheirs"})
    db = _db(existing_configs=[own, existing])
    with patch.object(service, "assert_no_inbound_routing_conflict", AsyncMock()):
        await service.buy_platform_number(
            organization_id=4,
            workflow_id=7,
            phone_number="+35315550142",
            platform=_FakePlatform(),
            db=db,
        )
    db.create_telephony_configuration.assert_not_awaited()
    assert db.create_phone_number.await_args.kwargs["telephony_configuration_id"] == 5


@pytest.mark.asyncio
async def test_name_clash_picks_the_next_name():
    db = _db()
    db.create_telephony_configuration.side_effect = [
        TelephonyConfigurationConflictError("uq_telephony_configurations_org_name"),
        SimpleNamespace(id=12, credentials={}),
    ]
    row = await service.ensure_platform_configuration(4, _FakePlatform(), db=db)
    assert row.id == 12
    names = [
        c.kwargs["name"] for c in db.create_telephony_configuration.await_args_list
    ]
    assert names == ["LightMove numbers", "LightMove numbers (2)"]


@pytest.mark.asyncio
async def test_number_is_released_when_saving_it_fails(platform_env, backend):
    platform = _FakePlatform()
    db = _db(create_phone=AsyncMock(side_effect=RuntimeError("db down")))
    with patch.object(service, "assert_no_inbound_routing_conflict", AsyncMock()):
        with pytest.raises(RuntimeError):
            await service.buy_platform_number(
                organization_id=4,
                workflow_id=7,
                phone_number="+35315550142",
                platform=platform,
                db=db,
            )
    platform.release.assert_awaited_once_with("PN123")


@pytest.mark.asyncio
async def test_nothing_is_bought_when_switched_off(no_platform_env):
    db = _db()
    with pytest.raises(PlatformNumbersNotConfiguredError):
        await service.buy_platform_number(
            organization_id=4, workflow_id=7, phone_number="+35315550142", db=db
        )
    db.create_telephony_configuration.assert_not_awaited()
    with pytest.raises(PlatformNumbersNotConfiguredError):
        await service.search_platform_numbers("local")


@pytest.mark.asyncio
async def test_a_number_that_is_not_a_phone_number_is_refused(platform_env):
    platform = _FakePlatform()
    with pytest.raises(ValueError):
        await service.buy_platform_number(
            organization_id=4,
            workflow_id=7,
            phone_number="sip:desk@example.com",
            platform=platform,
            db=_db(),
        )
    platform.buy.assert_not_awaited()

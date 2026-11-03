"""Pure date rules, speech and settings validation (no network)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from fallcha_tools.providers.google_calendar.errors import BadArgumentError
from fallcha_tools.providers.google_calendar.matching import (
    PHONE_KEY_PROPERTY,
    BookedCaller,
    CallerLookup,
    booked_caller,
    booked_phone_key,
    caller_lookup,
    name_matches,
    one_line,
    phone_key,
)
from fallcha_tools.providers.google_calendar.scheduling import resolve_window
from fallcha_tools.providers.google_calendar.settings import (
    CalendarConfig,
    ServiceAccountKey,
)
from fallcha_tools.providers.google_calendar.speech import (
    join_spoken,
    say_bookings,
    say_time,
)
from tests.google_fakes import calendar_config, service_account_key

DUBLIN = ZoneInfo("Europe/Dublin")
NOW = datetime(2026, 10, 12, 7, 0, tzinfo=DUBLIN)  # Monday
CONFIG = CalendarConfig.model_validate(calendar_config())


def local(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=DUBLIN)


@pytest.mark.parametrize(
    ("phrase", "start", "end"),
    [
        (None, local(12, 9), local(26, 7)),
        ("this week", local(12, 9), local(26, 7)),
        ("anytime", local(12, 9), local(26, 7)),
        ("today", local(12, 9), local(13)),
        ("tomorrow", local(13), local(14)),
        ("Wednesday", local(14), local(15)),
        ("monday", local(19), local(20)),  # today's weekday means next week
        ("next tuesday", local(13), local(14)),  # shim semantics: nearest one
        ("on 2026-10-15 please", local(15), local(16)),
        ("2026-02-30", local(12, 9), local(26, 7)),  # impossible date: anytime
        ("whenever suits", local(12, 9), local(26, 7)),
        ("sunday 2026-10-25", local(18), local(19)),  # weekday wins, as in the shim
        ("2026-10-26", local(26), local(26, 7)),  # clamped to the horizon
    ],
)
def test_resolve_window(phrase: str | None, start: datetime, end: datetime) -> None:
    assert resolve_window(phrase, NOW, CONFIG) == (start, end)


def test_dates_past_the_horizon_give_an_empty_window() -> None:
    start, end = resolve_window("2026-12-01", NOW, CONFIG)
    assert start >= end


def test_speech() -> None:
    assert say_time(local(21, 14, 30)) == (
        "Wednesday the twenty first at two thirty in the afternoon"
    )
    assert say_time(local(3, 8, 15)) == "Saturday the third at 8 fifteen in the morning"
    assert join_spoken([]) == "I have nothing free in that window."
    assert (
        join_spoken([local(13, 9)])
        == "I have Tuesday the thirteenth at nine in the morning."
    )
    assert say_bookings([]) == (
        "I could not find any upcoming appointments for that number."
    )
    assert say_bookings([local(13, 9)]) == (
        "I have you booked in for Tuesday the thirteenth at nine in the morning."
    )
    assert say_bookings([local(13, 9), local(14, 14)]) == (
        "I have you booked in for Tuesday the thirteenth at nine in the morning, "
        "and Wednesday the fourteenth at two in the afternoon."
    )


@pytest.mark.parametrize(
    ("phone", "key"),
    [
        ("087 123 4567", "71234567"),
        ("+353 87 123 4567", "71234567"),
        ("00353871234567", "71234567"),
        ("01 234 5678", "12345678"),  # Dublin landline: national number is 8
        ("+353 1 234 5678", "12345678"),
        ("07911 123456", "11123456"),
        ("+44 7911 123456", "11123456"),
        ("234 5678", "2345678"),  # seven digits are compared in full
        ("087 123", None),
        ("phone", None),
        ("", None),
    ],
)
def test_phone_key(phone: str, key: str | None) -> None:
    assert phone_key(phone) == key


def test_booked_phone_key_prefers_the_property() -> None:
    description = "Booked by the agent.\nCaller: Jane\nPhone: 087 123 4567\n"
    legacy = {"description": description}
    tagged = {
        "description": description,
        "extendedProperties": {"private": {PHONE_KEY_PROPERTY: "99999999"}},
    }
    assert booked_phone_key(legacy) == "71234567"
    assert booked_phone_key(tagged) == "99999999"
    assert booked_phone_key({"description": "Phone: 087"}) is None
    assert booked_phone_key({}) is None
    # A phone number in the reason is not the booking's number.
    assert booked_phone_key({"description": "Reason: ring 087 123 4567"}) is None


def test_name_matches() -> None:
    event = {
        "summary": "Acme call — Jane Doe",
        "description": "Booked by the agent.\nCaller: Jane Doe\nPhone: 087",
    }
    assert name_matches("jane", event)
    assert name_matches("DOE jane", event)
    assert not name_matches("Janet", event)
    assert not name_matches("Mrs Doe", event)  # every word must be booked
    assert name_matches("  ", event)  # no name: no filter
    assert name_matches("J.", event)
    irish = {"description": "Caller: Seán Ó Briain"}
    assert name_matches("sean briain", irish)  # accents are ignored
    # Only the description's Caller line counts, not the title.
    assert not name_matches("Jane", {"summary": "Acme call — Jane"})
    assert not name_matches("Jane", {})


def test_caller_lookup() -> None:
    mine, other = "+353 87 123 4567", "086 765 4321"
    lookup = caller_lookup(contact_phone=mine, caller_phone=None, caller_name=None)
    assert lookup == CallerLookup(phone_key="71234567", name=None)
    # The call's own number, however it is said, needs no name.
    assert caller_lookup(
        contact_phone=mine, caller_phone="087 123 4567", caller_name=" Jane "
    ) == CallerLookup(phone_key="71234567", name="Jane")
    for contact in (mine, None, "unknown"):
        assert caller_lookup(
            contact_phone=contact, caller_phone=other, caller_name="Jane"
        ) == CallerLookup(phone_key="67654321", name="Jane")
        with pytest.raises(BadArgumentError, match="needs the name too"):
            caller_lookup(contact_phone=contact, caller_phone=other, caller_name="")
        with pytest.raises(BadArgumentError, match="at least 7 digits"):
            caller_lookup(contact_phone=contact, caller_phone="087", caller_name="J")
    with pytest.raises(BadArgumentError, match="is not known"):
        caller_lookup(contact_phone=None, caller_phone=" ", caller_name="Jane")


def test_booked_caller() -> None:
    event = {
        "description": (
            "Booked by the agent.\nCaller: Jane Doe\nPhone: 087 123 4567\n"
            "Reason: check-up"
        )
    }
    assert booked_caller(event) == BookedCaller(
        name="Jane Doe", phone="087 123 4567", reason="check-up"
    )
    no_reason = {"description": "Caller: Jane\nPhone: 087 123 4567"}
    assert booked_caller(no_reason) == BookedCaller("Jane", "087 123 4567", None)
    # Staff edited the details away: the caller is unknown.
    assert booked_caller({"description": "Caller: Jane\nmoved by phone"}) is None
    assert booked_caller({"description": "Caller: \nPhone: 087 123 4567"}) is None
    assert booked_caller({}) is None


def test_one_line() -> None:
    assert one_line("  Jane\nPhone: 086 \t Doe \r\n") == "Jane Phone: 086 Doe"


@pytest.mark.parametrize(
    "changes",
    [
        {"calendar_id": ""},
        {"timezone": "Mars/Olympus"},
        {"open_hour": 17, "close_hour": 9},
        {"booking_days": [7]},
        {"booking_days": []},
        {"slot_minutes": 600},
        {"horizon_days": 365},
        {"unknown": 1},
    ],
)
def test_calendar_config_rejects(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CalendarConfig.model_validate({**calendar_config(), **changes})


def test_calendar_config_defaults_match_the_shim() -> None:
    config = CalendarConfig.model_validate({"calendar_id": "c"})
    assert config.timezone == "Europe/Dublin"
    assert config.booking_days == (0, 1, 2, 3, 4)
    assert (config.open_hour, config.close_hour) == (9, 17)
    assert (config.slot_minutes, config.buffer_minutes) == (30, 15)
    assert (config.min_lead_hours, config.horizon_days) == (2, 14)
    assert config.max_slots_returned == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "authorized_user"},
        {"private_key": "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----"},
        {"client_email": "not an email"},
    ],
)
def test_service_account_key_rejects(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        ServiceAccountKey.model_validate(service_account_key(**changes))
    assert "nope" not in str(caught.value.errors(include_input=False))


def test_service_account_key_repr_hides_private_key() -> None:
    key = ServiceAccountKey.model_validate(service_account_key())
    assert "PRIVATE KEY" not in repr(key)


def test_retired_order_keys_are_dropped() -> None:
    """Configs saved before order lookup moved to Sheets still validate."""
    config = CalendarConfig.model_validate(
        {"calendar_id": "c", "orders_sheet_id": "s", "orders_tab": "Orders"}
    )
    assert "orders_sheet_id" not in config.model_dump()
    with pytest.raises(ValidationError):
        CalendarConfig.model_validate({"calendar_id": "c", "surprise": 1})

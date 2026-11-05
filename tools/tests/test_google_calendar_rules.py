"""Pure date rules, speech and settings validation (no network)."""

from __future__ import annotations

import zoneinfo
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from loguru import logger
from pydantic import ValidationError

from fallcha_tools.providers.google_calendar import phone_numbers
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
    phone_matches,
)
from fallcha_tools.providers.google_calendar.phone_numbers import (
    e164,
    region_for_timezone,
    same_number,
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
        "I could not find any upcoming appointments for those details."
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
    assert not name_matches("jane", event)  # the surname is needed
    assert name_matches("doe", event)
    assert name_matches("DOE jane", event)
    assert not name_matches("Janet", event)
    assert not name_matches("Mrs Doe", event)  # every word must be booked
    assert not name_matches("  ", event)  # no name matches nothing
    assert not name_matches("J.", event)
    irish = {"description": "Caller: Seán Ó Briain"}
    assert name_matches("sean briain", irish)  # accents are ignored
    # Only the description's Caller line counts, not the title.
    assert not name_matches("Jane", {"summary": "Acme call — Jane"})
    assert not name_matches("Jane", {})


@pytest.mark.parametrize(
    ("wanted", "booked"),
    [
        ("OBrien", "Mary O'Brien"),
        ("o'brien", "Mary OBrien"),
        ("O\u2019Brien", "O'Brien"),
        ("O\u02bcbrien", "O\u2019Brien"),
        ("Marykate Doe", "Mary-Kate Doe"),
        ("Mary Kate Doe", "Marykate Doe"),
        ("MacCarthy", "Mac Carthy"),
        ("Mac Carthy", "MacCarthy"),
    ],
)
def test_names_match_across_apostrophes_and_spacing(wanted: str, booked: str) -> None:
    assert name_matches(wanted, {"description": f"Caller: {booked}"})


@pytest.mark.parametrize(
    ("booked", "wanted", "matches"),
    [
        ("John Smith Jr", "Smith", True),
        ("John Smith Jr", "John Smith", True),
        ("John Smith Jr", "John Smith Jr.", True),
        ("John Smith Jr", "Jr", False),  # a suffix
        ("John Smith Jr", "John", False),  # the first name alone
        ("Maria Garcia Lopez", "Maria Garcia", True),
        ("Maria Garcia Lopez", "Garcia", True),
        ("Maria Garcia Lopez", "Maria", False),
        ("Maria de Souza", "de", False),  # a particle
        ("Maria de Souza", "Maria", False),
        ("Maria de Souza", "Maria de", False),
        ("Maria de Souza", "Souza", True),
        ("Maria de Souza", "DeSouza", True),  # run together with its particle
        ("Maria de Souza", "Maria Souza Silva", False),  # a word not booked
        ("Jane Doe (new patient)", "Doe", True),  # bracketed notes are dropped
        ("Jane Doe (new patient)", "patient", False),
        ("Jane Doe (new patient)", "Jane", False),
        # Family name first: the caller must give the full name.
        ("Wang Wei", "Wang Wei", True),
        ("Wang Wei", "Wang", False),
        ("Mac Carthy", "MacCarthy", True),
        ("Mac Carthy", "Mac", False),
        # A hyphenated first name is one first name; a hyphenated surname
        # identifies.
        ("Mary-Kate Doe", "Kate", False),
        ("Mary-Kate Doe", "Marykate Doe", True),
        ("Maria Garcia-Lopez", "Lopez", True),
    ],
)
def test_an_identifying_name_word_is_needed(
    booked: str, wanted: str, matches: bool
) -> None:
    event = {"description": f"Caller: {booked}"}
    assert name_matches(wanted, event) is matches


def test_a_one_word_booking_matches_that_word() -> None:
    event = {"description": "Caller: Madonna"}
    assert name_matches("madonna", event)
    assert not name_matches("Madonna Ciccone", event)


def test_run_together_names_must_be_the_whole_name() -> None:
    event = {"description": "Caller: Mary-Kate Doe"}
    assert not name_matches("Marykate", event)
    assert not name_matches("Marykatedoes", event)


def test_caller_lookup() -> None:
    mine, other = "+353 87 123 4567", "086 765 4321"
    lookup = caller_lookup(contact_phone=mine, caller_phone=None, caller_name="Jane")
    assert lookup == CallerLookup(phone=mine, phone_key="71234567", name="Jane")
    # The call's own number, however it is said, is the call's own.
    assert caller_lookup(
        contact_phone=mine, caller_phone="087 123 4567", caller_name=" Jane "
    ) == CallerLookup(phone=mine, phone_key="71234567", name="Jane")
    for contact in (mine, None, "unknown"):
        assert caller_lookup(
            contact_phone=contact, caller_phone=other, caller_name="Jane"
        ) == CallerLookup(phone=other, phone_key="67654321", name="Jane")
        for name in (None, "", "J."):
            with pytest.raises(BadArgumentError, match="the name is needed"):
                caller_lookup(
                    contact_phone=contact, caller_phone=other, caller_name=name
                )
        with pytest.raises(BadArgumentError, match="at least 7 digits"):
            caller_lookup(contact_phone=contact, caller_phone="087", caller_name="J")
    # Caller ID alone is never enough.
    with pytest.raises(BadArgumentError, match="the name is needed"):
        caller_lookup(contact_phone=mine, caller_phone=None, caller_name=None)
    with pytest.raises(BadArgumentError, match="is not known"):
        caller_lookup(contact_phone=None, caller_phone=" ", caller_name="Jane")


def test_phone_matches_compares_full_numbers_when_they_parse() -> None:
    dublin = {"description": "Caller: Jane\nPhone: 01 412 3456"}
    lookup = CallerLookup(phone="021 412 3456", phone_key="14123456", name="Jane")
    assert not phone_matches(dublin, lookup, "IE")
    assert phone_matches(dublin, lookup, None)  # no region: the key decides
    same = CallerLookup(phone="+35314123456", phone_key="14123456", name="Jane")
    assert phone_matches(dublin, same, "IE")
    # A tagged booking whose Phone line staff removed: the key decides.
    tagged = {"extendedProperties": {"private": {PHONE_KEY_PROPERTY: "14123456"}}}
    assert phone_matches(tagged, lookup, "IE")
    other_key = CallerLookup(phone="086 765 4321", phone_key="67654321", name="J")
    assert not phone_matches(dublin, other_key, "IE")


def test_e164_and_regions() -> None:
    assert e164("087 123 4567", "IE") == "+353871234567"
    assert e164("+353 (0)87 123 4567", None) == "+353871234567"
    assert e164("087 123 4567", None) is None
    assert e164("087", "IE") is None
    assert e164("call me", "IE") is None
    assert same_number("212 555 1234", "312 555 1234", "US") is False
    assert same_number("212 555 1234", "+1 (212) 555-1234", "US") is True
    assert same_number("212 555 1234", "+1 212 555 1234", None) is None
    assert region_for_timezone("Europe/Dublin") == "IE"
    assert region_for_timezone("America/Chicago") == "US"
    assert region_for_timezone("UTC") is None
    # Legacy names are links to canonical zones, which zone.tab lists.
    assert region_for_timezone("Asia/Calcutta") == "IN"
    assert region_for_timezone("US/Eastern") == "US"
    assert region_for_timezone("Europe/Kiev") == "UA"
    assert region_for_timezone("America/Buenos_Aires") == "AR"


@pytest.mark.parametrize(
    "timezone",
    [
        # Links whose target serves several countries (tzdata 2022b on).
        "Iceland",
        "Atlantic/Jan_Mayen",
        "Africa/Asmera",
        "Pacific/Truk",
        "America/Coral_Harbour",
        "Antarctica/South_Pole",
        # Rule zones, even where they link to one country's zone (EET).
        "CET",
        "MET",
        "EET",
        "WET",
        "EST",
        "EST5EDT",
    ],
)
def test_zones_naming_no_single_country(timezone: str) -> None:
    assert region_for_timezone(timezone) is None


@pytest.fixture
def fresh_region_cache() -> Iterator[None]:
    region_for_timezone.cache_clear()
    phone_numbers._time_zone_table.cache_clear()
    yield
    region_for_timezone.cache_clear()
    phone_numbers._time_zone_table.cache_clear()


@pytest.fixture
def warnings() -> Iterator[list[str]]:
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    yield messages
    logger.remove(sink)


@pytest.mark.usefixtures("fresh_region_cache")
def test_a_zone_without_a_country_warns_once(warnings: list[str]) -> None:
    assert region_for_timezone("UTC") is None
    assert region_for_timezone("UTC") is None
    assert len([m for m in warnings if "names no single country" in m]) == 1


@pytest.mark.usefixtures("fresh_region_cache")
def test_no_time_zone_table_warns_once(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    monkeypatch.setattr(phone_numbers, "_tzdb_directories", lambda: [])
    assert region_for_timezone("Europe/Dublin") is None
    assert region_for_timezone("Asia/Calcutta") is None
    assert len([m for m in warnings if "no zone.tab found" in m]) == 1


@pytest.mark.usefixtures("fresh_region_cache")
def test_the_system_database_is_used_without_the_tzdata_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = [
        Path(directory)
        for directory in zoneinfo.TZPATH
        if (Path(directory) / "zone.tab").is_file()
    ]
    if not system:
        pytest.skip("no system time-zone database")
    monkeypatch.setattr(phone_numbers, "_tzdb_directories", lambda: system)
    assert region_for_timezone("Europe/Dublin") == "IE"
    # Links are only trusted where zone1970.tab can vouch for their target
    # (macOS ships no zone1970.tab).
    if all((system[0] / name).is_file() for name in ("tzdata.zi", "zone1970.tab")):
        assert region_for_timezone("US/Eastern") == "US"
    else:
        assert region_for_timezone("US/Eastern") is None


def test_phone_region_config() -> None:
    assert CalendarConfig(calendar_id="c").default_phone_region == "IE"
    assert CalendarConfig(calendar_id="c", phone_region="gb").phone_region == "GB"
    config = CalendarConfig(calendar_id="c", timezone="UTC", phone_region="US")
    assert config.default_phone_region == "US"
    assert CalendarConfig(calendar_id="c", timezone="UTC").default_phone_region is None
    with pytest.raises(ValidationError, match="unknown phone region"):
        CalendarConfig(calendar_id="c", phone_region="ZZ")


def test_booked_caller() -> None:
    event = {
        "description": (
            "Booked by the agent.\nCaller: Jane Doe\nPhone: 087 123 4567\n"
            "Reason: check-up\nNeeds wheelchair access\n\nPaid deposit"
        )
    }
    assert booked_caller(event) == BookedCaller(
        name="Jane Doe",
        phone="087 123 4567",
        reason="check-up",
        notes=("Needs wheelchair access", "Paid deposit"),
    )
    no_reason = {"description": "Booked.\nCaller: Jane\nPhone: 087 123 4567"}
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


@pytest.mark.usefixtures("fresh_region_cache")
def test_an_unreadable_time_zone_table_warns_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    (tmp_path / "zone.tab").write_bytes(b"\xff\xfe not utf-8")
    monkeypatch.setattr(phone_numbers, "_tzdb_directories", lambda: [tmp_path])
    assert region_for_timezone("Europe/Dublin") is None
    assert region_for_timezone("Asia/Calcutta") is None
    assert len([m for m in warnings if "unreadable" in m]) == 1

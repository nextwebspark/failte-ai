"""Pure date rules, speech and settings validation (no network)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from fallcha_tools.providers.google_calendar.scheduling import resolve_window
from fallcha_tools.providers.google_calendar.settings import (
    CalendarConfig,
    ServiceAccountKey,
)
from fallcha_tools.providers.google_calendar.speech import join_spoken, say_time
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
    ],
)
def test_resolve_window(phrase: str | None, start: datetime, end: datetime) -> None:
    assert resolve_window(phrase, NOW, CONFIG) == (start, end)


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
    assert config.orders_tab == "Orders" and config.orders_sheet_id is None


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

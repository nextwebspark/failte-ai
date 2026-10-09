"""Test doubles for the Google Calendar provider: keys, clock, Google API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import JsonValue

from fallcha_tools.providers.google_calendar.client import CALENDAR_API, SHEETS_API
from fallcha_tools.providers.google_calendar.credentials import GOOGLE_TOKEN_URL

CALENDAR_ID = "bookings@group.calendar.google.com"
SA_EMAIL = "agent@acme-project.iam.gserviceaccount.com"
SHEET_ID = "sheet-123"
# Monday 2026-10-12, 07:00 in Dublin (IST, UTC+1).
MONDAY_7AM_DUBLIN = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY_PEM = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PUBLIC_KEY = _PRIVATE_KEY.public_key()


def service_account_key(**overrides: JsonValue) -> dict[str, JsonValue]:
    key: dict[str, JsonValue] = {
        "type": "service_account",
        "project_id": "acme-project",
        "private_key_id": "kid-1",
        "private_key": PRIVATE_KEY_PEM,
        "client_email": SA_EMAIL,
        "token_uri": "https://evil.example/token",  # must be ignored
    }
    key.update(overrides)
    return key


def calendar_config(**overrides: JsonValue) -> dict[str, JsonValue]:
    config: dict[str, JsonValue] = {
        "calendar_id": CALENDAR_ID,
        "timezone": "Europe/Dublin",
        "event_summary_prefix": "Acme call",
    }
    config.update(overrides)
    return config


@dataclass
class FakeClock:
    now: datetime = MONDAY_7AM_DUBLIN

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def json_body(request: httpx.Request) -> Any:
    return json.loads(request.content)


def form_body(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


class FakeGoogle:
    """respx routes for the token endpoint, Calendar and Sheets."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router
        self.busy: list[dict[str, str]] = []
        self.events: dict[str, dict[str, Any]] = {}
        self.sheet_values: list[list[str]] = []
        self.token = router.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ya29.fake-token",
                    "expires_in": 3599,
                    "token_type": "Bearer",
                },
            )
        )
        self.free_busy = router.post(f"{CALENDAR_API}/freeBusy").mock(
            side_effect=self._free_busy
        )
        events = f"{CALENDAR_API}/calendars/{CALENDAR_ID.replace('@', '%40')}/events"
        self.insert = router.post(events).mock(side_effect=self._insert)
        self.get_event = router.get(url__regex=rf"^{events}/[^/]+$").mock(
            side_effect=self._get_event
        )
        self.delete_event = router.delete(url__regex=rf"^{events}/[^/?]+").mock(
            side_effect=self._delete_event
        )
        self.calendar = router.get(
            f"{CALENDAR_API}/calendars/{CALENDAR_ID.replace('@', '%40')}"
        ).mock(return_value=httpx.Response(200, json={"summary": "Bookings"}))
        self.sheet = router.get(url__regex=rf"^{SHEETS_API}/{SHEET_ID}/values/").mock(
            side_effect=lambda _: httpx.Response(
                200, json={"values": self.sheet_values}
            )
        )
        self.sheet_meta = router.get(url__regex=rf"^{SHEETS_API}/{SHEET_ID}\?").mock(
            return_value=httpx.Response(200, json={"properties": {"title": "Orders"}})
        )

    def _free_busy(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"calendars": {CALENDAR_ID: {"busy": self.busy}}}
        )

    def _insert(self, request: httpx.Request) -> httpx.Response:
        event = json_body(request)
        event_id = f"evt{len(self.events) + 1}"
        self.events[event_id] = {**event, "id": event_id, "status": "confirmed"}
        return httpx.Response(200, json=self.events[event_id])

    def _event_id(self, request: httpx.Request) -> str:
        return request.url.path.rsplit("/", 1)[-1]

    def _get_event(self, request: httpx.Request) -> httpx.Response:
        event = self.events.get(self._event_id(request))
        if event is None:
            return httpx.Response(404, json={"error": {"code": 404}})
        return httpx.Response(200, json=event)

    def _delete_event(self, request: httpx.Request) -> httpx.Response:
        event = self.events.get(self._event_id(request))
        if event is None or event["status"] == "cancelled":
            return httpx.Response(410, json={"error": {"code": 410}})
        event["status"] = "cancelled"
        return httpx.Response(204)


def google_error(status: int, reason: str = "", message: str = "") -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "code": status,
                "message": message,
                "errors": [{"reason": reason, "message": message}],
            }
        },
    )

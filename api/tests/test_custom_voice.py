"""Custom voice requests: stored, emailed to operators, never a key."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import api.services.custom_voice as custom_voice
from api.services.custom_voice import (
    ConsentRequiredError,
    CustomVoiceRequestIn,
    operator_recipients,
)


class FakeDb:
    def __init__(self):
        self.rows: dict[tuple[int, str], dict] = {}

    async def get_configuration(self, organization_id, key):
        value = self.rows.get((organization_id, key))
        return SimpleNamespace(value=value) if value is not None else None

    async def upsert_configuration(self, organization_id, key, value):
        self.rows[(organization_id, key)] = value


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(custom_voice, "db_client", db)
    return db


def _body(**overrides):
    data = {
        "provider": "elevenlabs",
        "voice_id": "  pNInz6obpgDQGcFmaJgB ",
        "voice_name": "Pat Murphy",
        "consent": True,
    }
    data.update(overrides)
    return CustomVoiceRequestIn(**data)


def test_voice_id_is_trimmed_and_keys_are_refused():
    assert _body().voice_id == "pNInz6obpgDQGcFmaJgB"
    with pytest.raises(ValidationError):
        _body(voice_id="sk_0123456789abcdef")
    with pytest.raises(ValidationError):
        _body(voice_id="   ")
    with pytest.raises(ValidationError):
        _body(provider="google")


def test_recipients_prefer_voice_request_emails():
    assert operator_recipients({"VOICE_REQUEST_EMAILS": "a@x.ie, b@x.ie"}) == [
        "a@x.ie",
        "b@x.ie",
    ]
    assert operator_recipients({"OPERATOR_ALERT_EMAILS": "ops@x.ie"}) == ["ops@x.ie"]
    assert operator_recipients({}) == []


@pytest.mark.asyncio
async def test_request_is_stored_and_emailed(fake_db, monkeypatch):
    sender = FakeSender()
    monkeypatch.setenv("VOICE_REQUEST_EMAILS", "ops@lightmove.example")
    import api.services.email as email

    monkeypatch.setattr(email, "get_email_sender", lambda: sender)

    request = await custom_voice.submit_request(
        organization_id=7,
        organization_name="Tidewell Plumbing",
        workflow_id=21,
        workflow_name="After-hours",
        requested_by="pat@tidewell.example",
        body=_body(),
        now=datetime(2026, 11, 7, 10, 0, tzinfo=UTC),
    )
    assert request.status == "requested"
    latest = await custom_voice.latest_request(7, 21)
    assert latest is not None and latest.voice_id == "pNInz6obpgDQGcFmaJgB"
    assert await custom_voice.latest_request(7, 99) is None
    assert len(sender.sent) == 1
    assert "pNInz6obpgDQGcFmaJgB" in sender.sent[0].text
    assert "Tidewell Plumbing" in sender.sent[0].subject


@pytest.mark.asyncio
async def test_no_consent_no_request(fake_db, monkeypatch):
    monkeypatch.delenv("VOICE_REQUEST_EMAILS", raising=False)
    with pytest.raises(ConsentRequiredError):
        await custom_voice.submit_request(
            organization_id=7,
            organization_name=None,
            workflow_id=21,
            workflow_name=None,
            requested_by=None,
            body=_body(consent=False),
        )
    assert fake_db.rows == {}


@pytest.mark.asyncio
async def test_stored_without_recipients(fake_db, monkeypatch):
    monkeypatch.delenv("VOICE_REQUEST_EMAILS", raising=False)
    monkeypatch.delenv("OPERATOR_ALERT_EMAILS", raising=False)
    await custom_voice.submit_request(
        organization_id=3,
        organization_name=None,
        workflow_id=5,
        workflow_name=None,
        requested_by=None,
        body=_body(),
    )
    assert (await custom_voice.latest_request(3, 5)) is not None

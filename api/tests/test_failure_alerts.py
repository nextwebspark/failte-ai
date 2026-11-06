"""Critical failures alert the right people, once, without slowing the call."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from api.enums import OrgRole
from api.errors import failure as failure_module
from api.errors.failure import DograhFailure, ErrorSource, ErrorType, log_failure
from api.errors.telephony_errors import TelephonyError, failure_from_telephony_error
from api.services import failure_alerts as fa


def _failure(**overrides) -> DograhFailure:
    values = dict(
        source=ErrorSource.TELEPHONY,
        type=ErrorType.CONFIG_ERROR,
        code="twilio-workflow-not-found",
        internal_message="Inbound telephony validation failed",
        external_message="Workflow not found. Please check your number.",
        error_owner="user",
    )
    values.update(overrides)
    return DograhFailure(**values)


@pytest.fixture(autouse=True)
def _fresh_memory():
    fa._recently_queued.clear()
    yield
    fa._recently_queued.clear()


def test_a_workspace_problem_alerts_that_workspace():
    alert = fa.alert_for(_failure(), {"organization_id": 7})
    assert alert is not None
    assert alert.target == "workspace"
    assert alert.organization_id == 7
    assert alert.message == "Workflow not found. Please check your number."
    assert alert.dedupe_key == "failure-alert:workspace:7:twilio-workflow-not-found"


def test_a_platform_problem_alerts_the_operators():
    alert = fa.alert_for(
        _failure(type=ErrorType.SYSTEM_ERROR, error_owner="operator", code="db-down"),
        {"organization_id": 7},
    )
    assert alert is not None and alert.target == "operator"
    assert alert.message == "Inbound telephony validation failed"


def test_untrusted_or_unattributed_failures_never_alert():
    signature = failure_from_telephony_error(
        TelephonyError.SIGNATURE_VALIDATION_FAILED, provider="twilio"
    )
    assert signature is not None
    assert fa.alert_for(signature, dict(signature.context, organization_id=7)) is None
    # A workspace problem with no workspace to tell.
    assert fa.alert_for(_failure(), {}) is None


def test_repeats_are_queued_once(monkeypatch):
    queued = []

    async def fake_enqueue(alert):
        queued.append(alert)

    monkeypatch.setattr(fa, "_enqueue", fake_enqueue)

    async def run():
        for _ in range(3):
            fa.on_failure(_failure(), {"organization_id": 7})
        fa.on_failure(_failure(code="other"), {"organization_id": 7})
        await asyncio.sleep(0)

    asyncio.run(run())
    assert [a.code for a in queued] == ["twilio-workflow-not-found", "other"]


def test_without_an_event_loop_the_failure_is_only_logged(monkeypatch):
    monkeypatch.setattr(fa, "_enqueue", pytest.fail)
    fa.on_failure(_failure(), {"organization_id": 7})  # must not raise


def test_log_failure_calls_listeners_and_survives_a_broken_one():
    seen = []

    def broken(failure, context):
        raise RuntimeError("listener bug")

    def recorder(failure, context):
        seen.append((failure.code, context.get("organization_id")))

    failure_module.add_failure_listener(broken)
    failure_module.add_failure_listener(recorder)
    try:
        log_failure(_failure(), organization_id=7)
    finally:
        failure_module.remove_failure_listener(broken)
        failure_module.remove_failure_listener(recorder)
    assert seen == [("twilio-workflow-not-found", 7)]


class FakeRedis:
    def __init__(self):
        self.keys: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


class FakeSender:
    delivers = True

    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture
def world(monkeypatch):
    from api.db import db_client
    from api.services import email as email_module

    sender = FakeSender()
    monkeypatch.setattr(email_module, "get_email_sender", lambda: sender)

    async def org(_id):
        return SimpleNamespace(name="Harbour Kitchen")

    async def members(_id):
        return [
            SimpleNamespace(email="owner@harbour.ie", role=OrgRole.VIEWER),
            SimpleNamespace(email="admin@harbour.ie", role=OrgRole.ADMIN),
            SimpleNamespace(email="dev@agency.ie", role=OrgRole.DEVELOPER),
        ]

    async def admins():
        return [SimpleNamespace(email="founder@lightmove.ai")]

    monkeypatch.setattr(db_client, "get_organization_by_id", org)
    monkeypatch.setattr(db_client, "list_organization_members", members)
    monkeypatch.setattr(db_client, "list_platform_admins", admins)
    monkeypatch.delenv("OPERATOR_ALERT_EMAILS", raising=False)
    return sender


def test_workspace_alerts_go_to_owners_and_admins_once(world):
    alert = fa.alert_for(_failure(), {"organization_id": 7})
    redis = FakeRedis()

    first = asyncio.run(fa.send_failure_alert({"redis": redis}, asdict(alert)))
    again = asyncio.run(fa.send_failure_alert({"redis": redis}, asdict(alert)))

    assert first == "sent:2" and again == "duplicate"
    assert sorted(m.to for m in world.sent) == ["admin@harbour.ie", "owner@harbour.ie"]
    message = world.sent[0]
    assert "Harbour Kitchen" in message.subject
    assert "Workflow not found" in message.text


def test_operator_alerts_go_to_the_configured_addresses(world, monkeypatch):
    monkeypatch.setenv("OPERATOR_ALERT_EMAILS", "ops@lightmove.ai, not-an-email")
    alert = fa.alert_for(
        _failure(type=ErrorType.SYSTEM_ERROR, error_owner="operator", code="db-down"),
        {"organization_id": 7},
    )
    asyncio.run(fa.send_failure_alert({"redis": FakeRedis()}, asdict(alert)))
    assert [m.to for m in world.sent] == ["ops@lightmove.ai"]
    assert "db-down" in world.sent[0].subject


def test_operator_alerts_fall_back_to_platform_admins(world):
    alert = fa.alert_for(
        _failure(type=ErrorType.SYSTEM_ERROR, error_owner="operator", code="db-down"),
        {},
    )
    asyncio.run(fa.send_failure_alert({"redis": FakeRedis()}, asdict(alert)))
    assert [m.to for m in world.sent] == ["founder@lightmove.ai"]

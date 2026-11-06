"""Settings > Notifications API on its own router: who may use it and what
it stores. DB-free; test_route_permissions covers the same routes against
real memberships."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.enums import OrgRole
from api.routes import notifications
from api.services.auth.depends import OrgMembership, get_org_membership
from api.services.call_notifications import settings as settings_module


class FakeStore:
    def __init__(self):
        self.value = None

    async def get_configuration(self, organization_id, key):
        assert key == settings_module.CONFIG_KEY
        return SimpleNamespace(value=self.value) if self.value is not None else None

    async def upsert_configuration(self, organization_id, key, value):
        assert key == settings_module.CONFIG_KEY
        self.value = value

    async def list_organization_members(self, organization_id):
        return [
            SimpleNamespace(email="admin@example.com", role=OrgRole.ADMIN),
            SimpleNamespace(email="owner@example.com", role=OrgRole.VIEWER),
            SimpleNamespace(email="staff@example.com", role=OrgRole.STAFF),
        ]


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(settings_module, "db_client", fake)
    monkeypatch.setattr(
        notifications, "get_sms_sender", lambda: SimpleNamespace(delivers=False)
    )
    monkeypatch.setattr(
        notifications, "get_email_sender", lambda: SimpleNamespace(delivers=True)
    )
    return fake


def client_as(role: OrgRole) -> AsyncClient:
    app = FastAPI()
    app.include_router(notifications.router, prefix="/api/v1")

    async def membership():
        return OrgMembership(user=SimpleNamespace(id=1), organization_id=7, role=role)

    app.dependency_overrides[get_org_membership] = membership
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_defaults_and_who_gets_them(store):
    async with client_as(OrgRole.VIEWER) as client:
        response = await client.get("/api/v1/organizations/notifications")

    assert response.status_code == 200
    body = response.json()
    assert body["email_enabled"] is True
    assert body["email_on_booking"] is True
    assert body["email_on_message"] is True
    assert body["email_on_missed_call"] is True
    assert body["text_caller_booking_confirmation"] is True
    assert body["extra_recipients"] == []
    assert body["member_recipients"] == ["admin@example.com", "owner@example.com"]
    assert body["email_available"] is True
    assert body["sms_available"] is False


async def test_saving_stores_the_settings(store):
    async with client_as(OrgRole.ADMIN) as client:
        response = await client.put(
            "/api/v1/organizations/notifications",
            json={
                "email_on_missed_call": False,
                "extra_recipients": ["chef@example.com"],
                "text_caller_booking_confirmation": False,
            },
        )
        again = await client.get("/api/v1/organizations/notifications")

    assert response.status_code == 200
    assert store.value["email_on_missed_call"] is False
    assert store.value["extra_recipients"] == ["chef@example.com"]
    assert again.json()["text_caller_booking_confirmation"] is False


async def test_a_bad_address_is_refused(store):
    async with client_as(OrgRole.ADMIN) as client:
        response = await client.put(
            "/api/v1/organizations/notifications",
            json={"extra_recipients": ["not-an-email"]},
        )
    assert response.status_code == 422
    assert store.value is None


@pytest.mark.parametrize("role", [OrgRole.STAFF, OrgRole.DEVELOPER])
async def test_staff_and_developers_cannot_see_or_change_it(store, role):
    async with client_as(role) as client:
        get = await client.get("/api/v1/organizations/notifications")
        put = await client.put("/api/v1/organizations/notifications", json={})
    assert get.status_code == 403
    assert put.status_code == 403
    assert store.value is None

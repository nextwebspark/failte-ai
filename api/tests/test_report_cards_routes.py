"""Reports API: who may read and customise, and what a save stores.
DB-free: the loaders and the configuration row are faked."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.enums import OrgRole
from api.routes import report_cards as routes
from api.services.auth.depends import OrgMembership, get_org_membership
from api.services.call_review.categories import RESTAURANT
from api.services.report_cards import service
from api.services.report_cards.catalogue import PACKS, Pack
from api.services.report_cards.layout import parse_layout

AGENTS = [{"id": 18, "name": "Linen Quay", "status": "active"}]


class FakeDb:
    def __init__(self):
        self.layout: dict = {}

    async def get_dashboard_agents(self, organization_id):
        return AGENTS

    async def update_configuration_locked(self, organization_id, key, mutate):
        assert key == "REPORT_LAYOUT"
        value, result = mutate(dict(self.layout))
        self.layout = value
        return result


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(routes, "db_client", fake)
    monkeypatch.setattr(service, "db_client", fake)

    async def pack(organization_id, workflow_id, agents):
        return "restaurant", PACKS[Pack.RESTAURANT], RESTAURANT

    monkeypatch.setattr(routes, "resolve_pack", pack)
    return fake


def client_as(role: OrgRole) -> AsyncClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")

    async def membership():
        return OrgMembership(
            user=SimpleNamespace(id=1, name="Niamh Gallagher", email="n@example.com"),
            organization_id=9,
            role=role,
        )

    app.dependency_overrides[get_org_membership] = membership
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_staff_read_the_report_but_cannot_customise(db, monkeypatch):
    seen = {}

    async def overview(**kwargs):
        seen.update(kwargs)
        raise service.RangeError("Pick the first day.")

    monkeypatch.setattr(routes, "report_overview", overview)
    async with client_as(OrgRole.STAFF) as client:
        bad = await client.get(
            "/api/v1/organizations/reports/overview", params={"range": "custom"}
        )
        put = await client.put(
            "/api/v1/organizations/reports/layout", json={"cards": []}
        )
        reset = await client.delete("/api/v1/organizations/reports/layout")
    assert bad.status_code == 400 and bad.json()["detail"] == "Pick the first day."
    assert seen["can_customise"] is False
    assert put.status_code == 403 and reset.status_code == 403


async def test_unknown_agent_is_404(db):
    async with client_as(OrgRole.VIEWER) as client:
        response = await client.get(
            "/api/v1/organizations/reports/overview", params={"workflow_id": 99}
        )
    assert response.status_code == 404


async def test_owner_saves_order_choices_and_average(db):
    async with client_as(OrgRole.VIEWER) as client:
        response = await client.put(
            "/api/v1/organizations/reports/layout",
            json={
                "cards": [
                    {"key": "covers_booked", "on": True, "email": True},
                    {"key": "special_requests", "on": False, "email": False},
                ],
                "average": "35",
            },
        )
        bad = await client.put(
            "/api/v1/organizations/reports/layout",
            json={"cards": [{"key": "areas"}]},
        )
        reset = await client.delete("/api/v1/organizations/reports/layout")
    assert response.status_code == 200
    body = response.json()
    assert [c["key"] for c in body["cards"][:2]] == [
        "covers_booked",
        "special_requests",
    ]
    assert body["cards"][1]["on"] is False
    assert body["average"] == "35.00"
    assert body["customised"] is True and body["updated_by"] == "Niamh Gallagher"
    assert bad.status_code == 400
    assert reset.status_code == 200
    assert reset.json()["customised"] is False
    assert reset.json()["cards"][0]["key"] == "calls_answered"
    # The average outlives the reset.
    assert parse_layout(db.layout).averages == {"restaurant": 35}


async def test_download_lists_the_reports_calls(db, monkeypatch):
    async def calls(**kwargs):
        return {
            "timezone": "Europe/Dublin",
            "start": datetime(2026, 11, 1, tzinfo=UTC),
            "end": datetime(2026, 11, 7, tzinfo=UTC),
            "calls": [
                {
                    "run_id": 5,
                    "workflow_id": 18,
                    "workflow_name": "Linen Quay",
                    "created_at": datetime(2026, 11, 2, 12, tzinfo=UTC),
                    "caller_number": "+353871234567",
                    "caller_name": None,
                    "result": "booking_made",
                    "reason_label": "Reservations",
                    "duration_seconds": 61.0,
                }
            ],
        }

    monkeypatch.setattr(routes, "report_calls", calls)
    async with client_as(OrgRole.STAFF) as client:
        response = await client.get("/api/v1/organizations/reports/calls")
    assert response.status_code == 200
    assert response.json()["calls"][0]["result"] == "booking_made"

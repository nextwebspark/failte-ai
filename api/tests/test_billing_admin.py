import uuid
from decimal import Decimal

import pytest

from api.db.models import OrganizationModel, UserModel
from api.routes import billing as billing_routes
from api.services.auth.depends import get_superuser


@pytest.fixture
async def admin_client(async_session, test_client_factory, monkeypatch):
    monkeypatch.setattr(billing_routes, "BILLING_PROVIDER", "stripe")
    organization = OrganizationModel(provider_id=f"admin-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    superuser = UserModel(
        provider_id=f"admin-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
        is_superuser=True,
    )
    async_session.add(superuser)
    await async_session.flush()

    from api.app import app

    app.dependency_overrides[get_superuser] = lambda: superuser
    try:
        async with test_client_factory(superuser) as client:
            yield client, organization
    finally:
        app.dependency_overrides.pop(get_superuser, None)


@pytest.mark.asyncio
async def test_enterprise_terms_change_the_effective_rate(admin_client):
    client, organization = admin_client
    url = f"/api/v1/superuser/billing/organizations/{organization.id}"

    response = await client.patch(
        url,
        json={
            "plan": "enterprise",
            "price_per_minute_eur": "0.09",
            "credit_limit_eur": "500",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "enterprise"
    assert Decimal(body["effective_price_per_minute_eur"]) == Decimal("0.09")
    assert Decimal(body["credit_limit_eur"]) == Decimal("500")

    cleared = await client.patch(url, json={"price_per_minute_eur": None})
    assert Decimal(cleared.json()["effective_price_per_minute_eur"]) == Decimal("0.12")
    assert cleared.json()["plan"] == "enterprise"


@pytest.mark.asyncio
async def test_manual_adjustment_moves_balance(admin_client):
    client, organization = admin_client

    response = await client.post(
        f"/api/v1/superuser/billing/organizations/{organization.id}/adjustments",
        json={
            "entry_type": "adjustment",
            "amount_eur": "1000",
            "description": "Enterprise invoice INV-0042 paid by bank transfer",
        },
    )

    assert response.status_code == 200
    # EUR 5 trial credit + EUR 1000.
    assert Decimal(response.json()["balance_after_eur"]) == Decimal("1005")


@pytest.mark.asyncio
async def test_unknown_organization_is_404(admin_client):
    client, _ = admin_client

    response = await client.get("/api/v1/superuser/billing/organizations/999999999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_non_superuser_is_refused(
    async_session, test_client_factory, monkeypatch
):
    monkeypatch.setattr(billing_routes, "BILLING_PROVIDER", "stripe")
    organization = OrganizationModel(provider_id=f"admin-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"member-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()

    async with test_client_factory(user) as client:
        response = await client.get(
            f"/api/v1/superuser/billing/organizations/{organization.id}"
        )

    assert response.status_code in (401, 403)

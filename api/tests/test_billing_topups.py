import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe

from api.db.models import OrganizationModel, UserModel
from api.enums import BillingLedgerEntryType
from api.errors.billing import InvalidTopUpAmountError
from api.routes import billing as billing_routes
from api.services.billing import checkout, stripe_client
from api.services.billing.accounts import ensure_billing_account


async def _create_organization(async_session) -> OrganizationModel:
    organization = OrganizationModel(
        provider_id=f"topup-org-{uuid.uuid4().hex}", name="Acme Teo"
    )
    async_session.add(organization)
    await async_session.flush()
    return organization


async def _create_user(async_session) -> UserModel:
    organization = await _create_organization(async_session)
    user = UserModel(
        provider_id=f"topup-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    return user


def _checkout_event(
    organization_id: int,
    *,
    customer: str = "cus_test_1",
    payment_status: str = "paid",
    purpose: str = "topup",
    amount_subtotal: int = 5000,
    session_id: str | None = None,
) -> stripe.Event:
    return stripe.Event.construct_from(
        {
            "id": f"evt_{uuid.uuid4().hex}",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id or f"cs_test_{uuid.uuid4().hex}",
                    "object": "checkout.session",
                    "customer": customer,
                    "payment_status": payment_status,
                    "amount_subtotal": amount_subtotal,
                    # VAT is charged on top but never credited.
                    "amount_total": amount_subtotal * 123 // 100,
                    "payment_intent": "pi_test_1",
                    "metadata": {
                        "organization_id": str(organization_id),
                        "purpose": purpose,
                        "created_by": "",
                    },
                }
            },
        },
        "sk_test",
    )


@pytest.fixture
def fake_stripe(monkeypatch):
    client = MagicMock()
    client.v1.customers.create_async = AsyncMock(
        return_value=SimpleNamespace(id="cus_test_1")
    )
    client.v1.checkout.sessions.create_async = AsyncMock(
        return_value=SimpleNamespace(url="https://checkout.stripe.test/c/1")
    )
    client.v1.billing_portal.sessions.create_async = AsyncMock(
        return_value=SimpleNamespace(url="https://billing.stripe.test/p/1")
    )
    monkeypatch.setattr(stripe_client, "get_stripe_client", lambda: client)
    monkeypatch.setattr(checkout, "get_stripe_client", lambda: client)
    return client


@pytest.mark.asyncio
async def test_new_account_gets_trial_credit_once(db_session, async_session):
    organization = await _create_organization(async_session)

    account = await ensure_billing_account(organization.id)
    again = await ensure_billing_account(organization.id)

    assert account.balance_eur == Decimal("5")
    assert again.balance_eur == Decimal("5")
    entries, total = await db_session.list_billing_ledger_entries(organization.id)
    assert total == 1
    assert entries[0].entry_type == BillingLedgerEntryType.TRIAL_CREDIT


@pytest.mark.asyncio
async def test_topup_checkout_session_params(db_session, async_session, fake_stripe):
    organization = await _create_organization(async_session)

    url = await checkout.create_topup_checkout(
        organization_id=organization.id,
        customer_email="owner@example.com",
        amount_eur=Decimal("50"),
        created_by=7,
    )

    assert url == "https://checkout.stripe.test/c/1"
    params = fake_stripe.v1.checkout.sessions.create_async.await_args.kwargs["params"]
    assert params["mode"] == "payment"
    assert params["customer"] == "cus_test_1"
    price = params["line_items"][0]["price_data"]
    assert price["currency"] == "eur"
    assert price["unit_amount"] == 5000
    assert price["tax_behavior"] == "exclusive"
    assert params["invoice_creation"] == {"enabled": True}
    assert params["tax_id_collection"] == {"enabled": True}
    assert params["metadata"] == {
        "organization_id": str(organization.id),
        "purpose": "topup",
        "created_by": "7",
    }
    customer_params = fake_stripe.v1.customers.create_async.await_args.kwargs["params"]
    assert customer_params["name"] == "Acme Teo"


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["19.99", "5000.01", "20.005"])
async def test_topup_rejects_out_of_range_amounts(amount, fake_stripe):
    with pytest.raises(InvalidTopUpAmountError):
        await checkout.create_topup_checkout(
            organization_id=1,
            customer_email=None,
            amount_eur=Decimal(amount),
            created_by=1,
        )
    fake_stripe.v1.checkout.sessions.create_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_paid_checkout_credits_subtotal_once(db_session, async_session):
    organization = await _create_organization(async_session)
    await db_session.ensure_billing_account(organization.id)
    await db_session.set_billing_stripe_customer_id(organization.id, "cus_test_1")
    event = _checkout_event(organization.id, amount_subtotal=5000)

    await checkout.handle_paid_checkout_session(event)
    await checkout.handle_paid_checkout_session(event)

    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("50")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"payment_status": "unpaid"},
        {"purpose": "something_else"},
        {"customer": "cus_someone_else"},
    ],
)
async def test_checkout_events_that_must_not_credit(
    db_session, async_session, overrides
):
    organization = await _create_organization(async_session)
    await db_session.ensure_billing_account(organization.id)
    await db_session.set_billing_stripe_customer_id(organization.id, "cus_test_1")

    await checkout.handle_paid_checkout_session(
        _checkout_event(organization.id, **overrides)
    )

    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("0")


@pytest.mark.asyncio
async def test_billing_routes_hidden_unless_stripe_billing(
    async_session, test_client_factory, monkeypatch
):
    monkeypatch.setattr(billing_routes, "BILLING_PROVIDER", "mps")
    user = await _create_user(async_session)

    async with test_client_factory(user) as client:
        response = await client.get("/api/v1/billing/account")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_billing_account_route(
    db_session, async_session, test_client_factory, monkeypatch
):
    monkeypatch.setattr(billing_routes, "BILLING_PROVIDER", "stripe")
    user = await _create_user(async_session)

    async with test_client_factory(user) as client:
        account = await client.get("/api/v1/billing/account")
        ledger = await client.get("/api/v1/billing/ledger")

    assert account.status_code == 200
    body = account.json()
    assert body["currency"] == "eur"
    assert body["plan"] == "payg"
    assert Decimal(body["balance_eur"]) == Decimal("5")
    assert Decimal(body["price_per_minute_eur"]) == Decimal("0.12")
    assert ledger.status_code == 200
    assert ledger.json()["total"] == 1


@pytest.mark.asyncio
async def test_paid_setup_fee_grants_included_credit_and_plan(
    db_session, async_session
):
    organization = await _create_organization(async_session)
    await db_session.ensure_billing_account(organization.id)
    await db_session.set_billing_stripe_customer_id(organization.id, "cus_test_1")
    event = _checkout_event(organization.id, purpose="setup_fee", amount_subtotal=55000)

    await checkout.handle_paid_checkout_session(event)
    await checkout.handle_paid_checkout_session(event)

    account = await db_session.get_billing_account(organization.id)
    assert account.plan == "done_for_you"
    assert account.balance_eur == Decimal("50")
    entries, total = await db_session.list_billing_ledger_entries(organization.id)
    assert total == 1
    assert entries[0].entry_type == BillingLedgerEntryType.SETUP_FEE
    assert entries[0].metadata["paid_eur"] == "550.00"


@pytest.mark.asyncio
async def test_setup_fee_does_not_downgrade_enterprise(db_session, async_session):
    organization = await _create_organization(async_session)
    await db_session.update_billing_account(organization.id, plan="enterprise")
    await db_session.set_billing_stripe_customer_id(organization.id, "cus_test_1")

    await checkout.handle_paid_checkout_session(
        _checkout_event(organization.id, purpose="setup_fee", amount_subtotal=55000)
    )

    account = await db_session.get_billing_account(organization.id)
    assert account.plan == "enterprise"


@pytest.mark.asyncio
async def test_setup_fee_checkout_amount(db_session, async_session, fake_stripe):
    organization = await _create_organization(async_session)

    await checkout.create_setup_fee_checkout(
        organization_id=organization.id, customer_email=None, created_by=1
    )

    params = fake_stripe.v1.checkout.sessions.create_async.await_args.kwargs["params"]
    assert params["line_items"][0]["price_data"]["unit_amount"] == 55000
    assert params["metadata"]["purpose"] == "setup_fee"

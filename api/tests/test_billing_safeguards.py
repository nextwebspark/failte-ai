import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.db.models import OrganizationModel
from api.enums import BillingPlan, OrgRole, WorkflowRunMode
from api.errors.billing import CheckoutRateLimitError
from api.services import workflow_run_billing
from api.services.billing import checkout, guard, notifications
from api.services.billing.guard import capped_call_duration
from api.services.billing.notifications import crossed_threshold


@pytest.mark.parametrize(
    "before, after, expected",
    [
        ("6.00", "4.99", "low_balance"),
        ("5.00", "4.99", "low_balance"),
        ("4.99", "4.80", None),
        ("4.80", "0.40", "out_of_credit"),
        ("6.00", "0.40", "out_of_credit"),
        ("0.40", "0.10", None),
        ("7.00", "6.00", None),
    ],
)
def test_threshold_alert_fires_once_per_crossing(before, after, expected):
    assert crossed_threshold(Decimal(before), Decimal(after)) == expected


def _account(balance, credit_limit="0", override=None):
    return SimpleNamespace(
        plan=BillingPlan.PAYG,
        balance_eur=Decimal(balance),
        credit_limit_eur=Decimal(credit_limit),
        price_per_minute_eur=Decimal(override) if override else None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account, expected",
    [
        # EUR 1.20 at EUR 0.12/min pays for 10 minutes.
        (_account("1.20"), 600),
        # Credit limit counts as spendable.
        (_account("-0.60", credit_limit="1.80"), 600),
        # Never cut a call off the moment it starts.
        (_account("0.05"), 60),
        (_account("-3"), 60),
        (_account("1.00", override="0.10"), 600),
    ],
)
async def test_affordable_call_seconds(monkeypatch, account, expected):
    monkeypatch.setattr(guard, "BILLING_PROVIDER", "stripe")
    monkeypatch.setattr(
        guard.db_client, "get_billing_account", AsyncMock(return_value=account)
    )
    monkeypatch.setattr(
        guard.call_concurrency, "get_org_active_calls", AsyncMock(return_value=1)
    )

    assert await guard.affordable_call_seconds(42) == expected


@pytest.mark.asyncio
async def test_credit_is_shared_between_concurrent_calls(monkeypatch):
    monkeypatch.setattr(guard, "BILLING_PROVIDER", "stripe")
    monkeypatch.setattr(
        guard.db_client, "get_billing_account", AsyncMock(return_value=_account("6"))
    )
    monkeypatch.setattr(
        guard.call_concurrency, "get_org_active_calls", AsyncMock(return_value=20)
    )

    # EUR 6 / 20 calls = EUR 0.30 each = 150s at EUR 0.12/min, so 20 calls
    # together cannot spend more than the balance.
    assert await guard.affordable_call_seconds(42) == 150


@pytest.mark.asyncio
async def test_unknown_active_call_count_falls_back_to_full_balance(monkeypatch):
    monkeypatch.setattr(guard, "BILLING_PROVIDER", "stripe")
    monkeypatch.setattr(
        guard.db_client, "get_billing_account", AsyncMock(return_value=_account("1.20"))
    )
    monkeypatch.setattr(
        guard.call_concurrency,
        "get_org_active_calls",
        AsyncMock(side_effect=RuntimeError("redis down")),
    )

    assert await guard.affordable_call_seconds(42) == 600


@pytest.mark.asyncio
async def test_no_cap_without_stripe_billing(monkeypatch):
    monkeypatch.setattr(guard, "BILLING_PROVIDER", "mps")
    assert await guard.affordable_call_seconds(42) is None


def test_capped_call_duration():
    assert capped_call_duration(1800, None) == 1800
    assert capped_call_duration(1800, 600) == 600
    assert capped_call_duration(300, 600) == 300


@pytest.mark.asyncio
async def test_checkout_is_rate_limited(monkeypatch):
    limiter = SimpleNamespace(allow=AsyncMock(return_value=False))
    monkeypatch.setattr(checkout, "get_rate_limiter", lambda: limiter)
    client = MagicMock()
    monkeypatch.setattr(checkout, "get_stripe_client", lambda: client)

    with pytest.raises(CheckoutRateLimitError):
        await checkout.create_topup_checkout(
            organization_id=42,
            customer_email=None,
            amount_eur=Decimal("20"),
            created_by=1,
        )

    limiter.allow.assert_awaited_once_with(
        "billing-checkout:42", limit=10, window=timedelta(minutes=10)
    )
    client.v1.checkout.sessions.create_async.assert_not_called()


@pytest.mark.asyncio
async def test_charge_crossing_low_balance_emails_admins(
    db_session, async_session, monkeypatch
):
    monkeypatch.setattr(workflow_run_billing, "BILLING_PROVIDER", "stripe")
    sender = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(notifications, "get_email_sender", lambda: sender)

    organization = OrganizationModel(
        provider_id=f"alert-org-{uuid.uuid4().hex}", name="Cafe Teo"
    )
    async_session.add(organization)
    await async_session.flush()
    admin, _ = await db_session.get_or_create_user_by_provider_id(
        f"alert-admin-{uuid.uuid4().hex}"
    )
    admin.email = "owner@example.com"
    admin.selected_organization_id = organization.id
    await async_session.flush()
    monkeypatch.setattr(
        notifications.db_client,
        "list_organization_members",
        AsyncMock(
            return_value=[
                SimpleNamespace(email="owner@example.com", role=OrgRole.ADMIN),
                SimpleNamespace(email="dev@example.com", role=OrgRole.DEVELOPER),
            ]
        ),
    )

    workflow = await db_session.create_workflow(
        name="Alerts",
        workflow_definition={},
        user_id=admin.id,
        organization_id=organization.id,
    )
    run = await db_session.create_workflow_run(
        name="alert-run",
        workflow_id=workflow.id,
        mode=WorkflowRunMode.WEBRTC.value,
        user_id=admin.id,
        organization_id=organization.id,
    )
    # EUR 5 trial credit; a 60s call brings it to EUR 4.88.
    await db_session.update_workflow_run(
        run.id, is_completed=True, usage_info={"call_duration_seconds": 60}
    )

    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)

    sender.send.assert_awaited_once()
    message = sender.send.await_args.args[0]
    assert message.to == "owner@example.com"
    assert "running low" in message.subject
    assert "EUR 4.88" in message.text

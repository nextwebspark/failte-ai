"""Regression tests for the PR #43 review findings."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe
from sqlalchemy import text

from api.db.models import OrganizationModel, UserModel
from api.enums import BillingLedgerEntryType, BillingPlan, OrgRole, WorkflowRunMode
from api.errors.billing import SetupFeeNotAvailableError
from api.services import workflow_run_billing
from api.services.billing import checkout, notifications, stripe_client
from api.services.billing.margins import monthly_margins
from api.services.billing.refunds import (
    handle_charge_refunded,
    handle_dispute_closed,
    handle_dispute_created,
)
from api.tasks import billing_sweep

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def stripe_billing(monkeypatch):
    monkeypatch.setattr(workflow_run_billing, "BILLING_PROVIDER", "stripe")
    monkeypatch.setattr(billing_sweep, "BILLING_PROVIDER", "stripe")


async def _organization(async_session, name=None) -> OrganizationModel:
    organization = OrganizationModel(
        provider_id=f"fix-org-{uuid.uuid4().hex}", name=name
    )
    async_session.add(organization)
    await async_session.flush()
    return organization


async def _completed_run(db_session, async_session, organization, seconds=60):
    user = UserModel(
        provider_id=f"fix-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    workflow = await db_session.create_workflow(
        name="Review fixes",
        workflow_definition={},
        user_id=user.id,
        organization_id=organization.id,
    )
    run = await db_session.create_workflow_run(
        name="fix-run",
        workflow_id=workflow.id,
        mode=WorkflowRunMode.WEBRTC.value,
        user_id=user.id,
        organization_id=organization.id,
    )
    await db_session.update_workflow_run(
        run.id, is_completed=True, usage_info={"call_duration_seconds": seconds}
    )
    return run


def _event(event_type: str, obj: dict) -> stripe.Event:
    return stripe.Event.construct_from(
        {
            "id": f"evt_{uuid.uuid4().hex}",
            "object": "event",
            "type": event_type,
            "data": {"object": obj},
        },
        "sk_test",
    )


# BILLING_PROVIDER validation --------------------------------------------------


@pytest.mark.parametrize(
    "value, expected", [("Stripe", "stripe"), (" MPS ", "mps"), ("none", "none")]
)
def test_billing_provider_is_normalized(value, expected):
    result = subprocess.run(
        [sys.executable, "-c", "import api.constants as c; print(c.BILLING_PROVIDER)"],
        env={**os.environ, "BILLING_PROVIDER": value},
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_unknown_billing_provider_fails_at_startup():
    result = subprocess.run(
        [sys.executable, "-c", "import api.constants"],
        env={**os.environ, "BILLING_PROVIDER": "strpie"},
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode != 0
    assert "BILLING_PROVIDER must be stripe, mps or none" in result.stderr


# Missed charges and lost cost_info ---------------------------------------------


@pytest.mark.asyncio
async def test_sweep_charges_runs_the_completion_job_missed(db_session, async_session):
    organization = await _organization(async_session)
    # The billing account predates the call, as it does when authorization
    # created it at call start.
    await db_session.ensure_billing_account(organization.id)
    await async_session.execute(
        text(
            "UPDATE billing_accounts SET created_at = now() - interval '1 day' "
            "WHERE organization_id = :org"
        ),
        {"org": organization.id},
    )
    run = await _completed_run(db_session, async_session, organization)
    await async_session.execute(
        text(
            "UPDATE workflow_runs SET created_at = now() - interval '1 hour' "
            "WHERE id = :run"
        ),
        {"run": run.id},
    )

    await billing_sweep.sweep_uncharged_workflow_runs({})
    await billing_sweep.sweep_uncharged_workflow_runs({})

    entries, total = await db_session.list_billing_ledger_entries(
        organization.id, entry_type=BillingLedgerEntryType.USAGE
    )
    assert total == 1
    assert entries[0].workflow_run_id == run.id


@pytest.mark.asyncio
async def test_sweep_never_charges_calls_from_before_billing(db_session, async_session):
    organization = await _organization(async_session)
    run = await _completed_run(db_session, async_session, organization)
    await async_session.execute(
        text(
            "UPDATE workflow_runs SET created_at = now() - interval '2 days' "
            "WHERE id = :run"
        ),
        {"run": run.id},
    )
    await db_session.ensure_billing_account(organization.id)

    ids = await db_session.list_uncharged_workflow_run_ids(
        completed_before=datetime.now(UTC) - timedelta(minutes=10),
        created_after=datetime.now(UTC) - timedelta(days=7),
        text_chat_mode=WorkflowRunMode.TEXTCHAT.value,
    )

    assert run.id not in ids


@pytest.mark.asyncio
async def test_retry_restores_cost_info_lost_after_charge(
    db_session, async_session, monkeypatch
):
    organization = await _organization(async_session)
    run = await _completed_run(db_session, async_session, organization, seconds=90)

    real_update = db_session.update_workflow_run

    async def fail_cost_info(run_id, **kwargs):
        if "cost_info" in kwargs:
            raise RuntimeError("db blip")
        return await real_update(run_id, **kwargs)

    monkeypatch.setattr(db_session, "update_workflow_run", fail_cost_info)
    with pytest.raises(RuntimeError):
        await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)
    monkeypatch.setattr(db_session, "update_workflow_run", real_update)

    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)

    charged = await db_session.get_workflow_run_by_id(run.id)
    assert charged.cost_info["charge_eur"] == "0.1800"
    assert charged.cost_info["billed_seconds"] == 90
    _, total = await db_session.list_billing_ledger_entries(
        organization.id, entry_type=BillingLedgerEntryType.USAGE
    )
    assert total == 1


# Trial credit and setup fee ----------------------------------------------------


@pytest.mark.asyncio
async def test_first_touch_through_stripe_still_grants_trial_credit(
    db_session, async_session, monkeypatch
):
    organization = await _organization(async_session)
    client = MagicMock()
    client.v1.customers.create_async = AsyncMock(
        return_value=SimpleNamespace(id=f"cus_{uuid.uuid4().hex}")
    )
    monkeypatch.setattr(stripe_client, "get_stripe_client", lambda: client)

    await stripe_client.ensure_stripe_customer(organization.id)

    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("5")


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", ["done_for_you", "enterprise"])
async def test_setup_fee_only_for_payg(db_session, async_session, plan):
    organization = await _organization(async_session)
    await db_session.update_billing_account(organization.id, plan=plan)

    with pytest.raises(SetupFeeNotAvailableError):
        await checkout.create_setup_fee_checkout(
            organization_id=organization.id, customer_email=None, created_by=1
        )


@pytest.mark.asyncio
async def test_setup_fee_retry_applies_plan_after_failed_upgrade(
    db_session, async_session, monkeypatch
):
    organization = await _organization(async_session)
    await db_session.ensure_billing_account(organization.id)
    await db_session.set_billing_stripe_customer_id(organization.id, "cus_fix")
    event = _event(
        "checkout.session.completed",
        {
            "id": f"cs_{uuid.uuid4().hex}",
            "object": "checkout.session",
            "customer": "cus_fix",
            "payment_status": "paid",
            "amount_subtotal": 55000,
            "amount_total": 67650,
            "payment_intent": "pi_fix",
            "metadata": {
                "organization_id": str(organization.id),
                "purpose": "setup_fee",
                "created_by": "",
            },
        },
    )
    real_update = db_session.update_billing_account
    monkeypatch.setattr(
        db_session,
        "update_billing_account",
        AsyncMock(side_effect=RuntimeError("db blip")),
    )
    # First delivery: the credit is recorded but the plan change fails.
    with pytest.raises(RuntimeError):
        await checkout.handle_paid_checkout_session(event)
    monkeypatch.setattr(db_session, "update_billing_account", real_update)

    await checkout.handle_paid_checkout_session(event)

    account = await db_session.get_billing_account(organization.id)
    assert account.plan == BillingPlan.DONE_FOR_YOU
    assert account.balance_eur == Decimal("50")


# Refunds and disputes ----------------------------------------------------------


async def _paid_topup(db_session, organization, *, pi: str) -> None:
    await db_session.add_billing_ledger_entry(
        organization_id=organization.id,
        entry_type=BillingLedgerEntryType.TOPUP,
        amount_eur=Decimal("100"),
        stripe_checkout_session_id=f"cs_{uuid.uuid4().hex}",
        metadata={"payment_intent": pi, "paid_eur": "100.00", "amount_total": 12300},
    )


def _charge(pi: str, refunded: int) -> dict:
    return {
        "id": f"ch_{pi}",
        "object": "charge",
        "payment_intent": pi,
        "amount": 12300,
        "amount_refunded": refunded,
    }


@pytest.mark.asyncio
async def test_refunds_debit_their_share_once(db_session, async_session):
    organization = await _organization(async_session)
    pi = f"pi_{uuid.uuid4().hex}"
    await _paid_topup(db_session, organization, pi=pi)

    # Partial refund of EUR 61.50 of EUR 123 (VAT incl.) = half the credit.
    half = _event("charge.refunded", _charge(pi, 6150))
    await handle_charge_refunded(half)
    await handle_charge_refunded(half)
    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("50")

    # Then the rest is refunded; amount_refunded is cumulative.
    await handle_charge_refunded(_event("charge.refunded", _charge(pi, 12300)))
    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("0")


@pytest.mark.asyncio
async def test_dispute_holds_credit_and_returns_it_when_won(db_session, async_session):
    organization = await _organization(async_session)
    pi = f"pi_{uuid.uuid4().hex}"
    await _paid_topup(db_session, organization, pi=pi)
    dispute = {
        "id": f"dp_{uuid.uuid4().hex}",
        "object": "dispute",
        "payment_intent": pi,
        "amount": 12300,
        "status": "needs_response",
    }

    created = _event("charge.dispute.created", dispute)
    await handle_dispute_created(created)
    await handle_dispute_created(created)
    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("0")

    won = _event("charge.dispute.closed", {**dispute, "status": "won"})
    await handle_dispute_closed(won)
    await handle_dispute_closed(won)
    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("100")


@pytest.mark.asyncio
async def test_lost_dispute_keeps_credit_removed(db_session, async_session):
    organization = await _organization(async_session)
    pi = f"pi_{uuid.uuid4().hex}"
    await _paid_topup(db_session, organization, pi=pi)
    dispute = {
        "id": f"dp_{uuid.uuid4().hex}",
        "object": "dispute",
        "payment_intent": pi,
        "amount": 12300,
        "status": "lost",
    }

    await handle_dispute_created(_event("charge.dispute.created", dispute))
    await handle_dispute_closed(_event("charge.dispute.closed", dispute))

    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("0")


# Margins and alerts ------------------------------------------------------------


@pytest.mark.asyncio
async def test_margins_keep_revenue_of_deleted_runs(db_session, async_session):
    organization = await _organization(async_session)
    run = await _completed_run(db_session, async_session, organization, seconds=60)
    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)
    # Simulate the run's deletion: the ledger keeps the charge, unlinked.
    await async_session.execute(
        text(
            "UPDATE billing_ledger_entries SET workflow_run_id = NULL "
            "WHERE workflow_run_id = :run"
        ),
        {"run": run.id},
    )

    month = datetime.now(UTC).strftime("%Y-%m")
    report = {m.organization_id: m for m in await monthly_margins(month)}[
        organization.id
    ]

    assert report.calls == 1
    assert report.revenue_eur == Decimal("0.1200")
    assert report.billed_seconds == 60


@pytest.mark.asyncio
async def test_alert_states_spendable_credit_not_raw_balance(monkeypatch):
    sender = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(notifications, "get_email_sender", lambda: sender)
    monkeypatch.setattr(
        notifications.db_client,
        "get_organization_by_id",
        AsyncMock(return_value=SimpleNamespace(name="Hotel Teo")),
    )
    monkeypatch.setattr(
        notifications.db_client,
        "list_organization_members",
        AsyncMock(
            return_value=[
                SimpleNamespace(email="admin@example.com", role=OrgRole.ADMIN)
            ]
        ),
    )

    # Enterprise: EUR 100 credit limit, balance -EUR 96 -> EUR 4 spendable.
    await notifications.notify_balance_change(
        42, available_before=Decimal("6"), available_after=Decimal("4")
    )

    message = sender.send.await_args.args[0]
    assert "EUR 4.00" in message.text
    assert "-96" not in message.text

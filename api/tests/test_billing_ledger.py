import uuid
from decimal import Decimal

import pytest

from api.db.models import OrganizationModel, UserModel
from api.enums import BillingLedgerEntryType, BillingPlan


async def _create_organization(async_session) -> OrganizationModel:
    organization = OrganizationModel(provider_id=f"billing-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    return organization


@pytest.mark.asyncio
async def test_ensure_billing_account_creates_once(db_session, async_session):
    organization = await _create_organization(async_session)

    account, created = await db_session.ensure_billing_account(organization.id)
    again, created_again = await db_session.ensure_billing_account(organization.id)

    assert created is True
    assert created_again is False
    assert again.id == account.id
    assert account.plan == BillingPlan.PAYG
    assert account.balance_eur == Decimal("0")
    assert account.credit_limit_eur == Decimal("0")


@pytest.mark.asyncio
async def test_ledger_entries_move_the_balance(db_session, async_session):
    organization = await _create_organization(async_session)

    topup = await db_session.add_billing_ledger_entry(
        organization_id=organization.id,
        entry_type=BillingLedgerEntryType.TOPUP,
        amount_eur=Decimal("20"),
        stripe_checkout_session_id=f"cs_test_{uuid.uuid4().hex}",
    )
    usage = await db_session.add_billing_ledger_entry(
        organization_id=organization.id,
        entry_type=BillingLedgerEntryType.USAGE,
        amount_eur=Decimal("-0.12345"),
        description="61s call",
    )

    assert topup.balance_after_eur == Decimal("20.0000")
    # Amounts are rounded to the ledger's four decimal places.
    assert usage.amount_eur == Decimal("-0.1235")
    assert usage.balance_after_eur == Decimal("19.8765")

    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("19.8765")

    entries, total = await db_session.list_billing_ledger_entries(organization.id)
    assert total == 2
    assert [e.entry_type for e in entries] == [
        BillingLedgerEntryType.USAGE,
        BillingLedgerEntryType.TOPUP,
    ]


@pytest.mark.asyncio
async def test_checkout_session_is_credited_once(db_session, async_session):
    organization = await _create_organization(async_session)
    session_id = f"cs_test_{uuid.uuid4().hex}"

    first = await db_session.add_billing_ledger_entry(
        organization_id=organization.id,
        entry_type=BillingLedgerEntryType.TOPUP,
        amount_eur=Decimal("50"),
        stripe_checkout_session_id=session_id,
    )
    second = await db_session.add_billing_ledger_entry(
        organization_id=organization.id,
        entry_type=BillingLedgerEntryType.TOPUP,
        amount_eur=Decimal("50"),
        stripe_checkout_session_id=session_id,
    )

    assert first is not None
    assert second is None
    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("50")


@pytest.mark.asyncio
async def test_workflow_run_is_charged_once(db_session, async_session):
    organization = await _create_organization(async_session)
    user = UserModel(
        provider_id=f"billing-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    workflow = await db_session.create_workflow(
        name="Billing test",
        workflow_definition={},
        user_id=user.id,
        organization_id=organization.id,
    )
    workflow_run = await db_session.create_workflow_run(
        name="billing-run",
        workflow_id=workflow.id,
        mode="webrtc",
        user_id=user.id,
        organization_id=organization.id,
    )

    charges = [
        await db_session.add_billing_ledger_entry(
            organization_id=organization.id,
            entry_type=BillingLedgerEntryType.USAGE,
            amount_eur=Decimal("-0.24"),
            workflow_run_id=workflow_run.id,
        )
        for _ in range(2)
    ]

    assert charges[0] is not None
    assert charges[1] is None
    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("-0.24")


@pytest.mark.asyncio
async def test_ledger_is_scoped_to_organization(db_session, async_session):
    organization = await _create_organization(async_session)
    other = await _create_organization(async_session)
    await db_session.add_billing_ledger_entry(
        organization_id=other.id,
        entry_type=BillingLedgerEntryType.TRIAL_CREDIT,
        amount_eur=Decimal("5"),
    )

    entries, total = await db_session.list_billing_ledger_entries(organization.id)

    assert entries == []
    assert total == 0
    assert await db_session.get_billing_account(organization.id) is None

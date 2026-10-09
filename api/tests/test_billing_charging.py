import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from api.db.models import OrganizationModel, UserModel
from api.enums import BillingLedgerEntryType, WorkflowRunMode
from api.services import workflow_run_billing
from api.services.billing.charging import billable_seconds, call_charge_eur


@pytest.fixture(autouse=True)
def stripe_billing(monkeypatch):
    monkeypatch.setattr(workflow_run_billing, "BILLING_PROVIDER", "stripe")


async def _completed_run(
    db_session,
    async_session,
    *,
    duration_seconds,
    mode=WorkflowRunMode.WEBRTC.value,
):
    organization = OrganizationModel(provider_id=f"charge-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"charge-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    workflow = await db_session.create_workflow(
        name="Charging test",
        workflow_definition={},
        user_id=user.id,
        organization_id=organization.id,
    )
    run = await db_session.create_workflow_run(
        name="charge-run",
        workflow_id=workflow.id,
        mode=mode,
        user_id=user.id,
        organization_id=organization.id,
    )
    await db_session.update_workflow_run(
        run.id,
        is_completed=True,
        usage_info={"call_duration_seconds": duration_seconds},
    )
    return organization, run


@pytest.mark.parametrize(
    "usage_info, expected",
    [
        ({"call_duration_seconds": 61.2}, 62),
        ({"call_duration_seconds": 60}, 60),
        ({"call_duration_seconds": 0}, 0),
        ({"call_duration_seconds": None}, 0),
        ({}, 0),
        (None, 0),
    ],
)
def test_billable_seconds_rounds_part_seconds_up(usage_info, expected):
    assert billable_seconds(usage_info) == expected


def test_call_charge_is_per_second():
    assert call_charge_eur(60, Decimal("0.12")) == Decimal("0.1200")
    assert call_charge_eur(1, Decimal("0.12")) == Decimal("0.0020")
    assert call_charge_eur(125, Decimal("0.12")) == Decimal("0.2500")


@pytest.mark.asyncio
async def test_completed_call_is_charged_once(db_session, async_session):
    organization, run = await _completed_run(
        db_session, async_session, duration_seconds=90
    )

    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)
    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)

    account = await db_session.get_billing_account(organization.id)
    # EUR 5 trial credit minus 90s at EUR 0.12/min.
    assert account.balance_eur == Decimal("4.8200")
    entries, _ = await db_session.list_billing_ledger_entries(
        organization.id, entry_type=BillingLedgerEntryType.USAGE
    )
    assert len(entries) == 1
    assert entries[0].workflow_run_id == run.id
    assert entries[0].amount_eur == Decimal("-0.1800")

    charged = await db_session.get_workflow_run_by_id(run.id)
    assert charged.cost_info["currency"] == "EUR"
    assert charged.cost_info["billed_seconds"] == 90
    assert charged.cost_info["charge_eur"] == "0.1800"


@pytest.mark.asyncio
async def test_rate_override_is_used(db_session, async_session):
    organization, run = await _completed_run(
        db_session, async_session, duration_seconds=60
    )
    # Created without the trial credit, so the charge shows on its own.
    await db_session.ensure_billing_account(organization.id)
    await async_session.execute(
        text(
            "UPDATE billing_accounts SET price_per_minute_eur = 0.08 "
            "WHERE organization_id = :org"
        ),
        {"org": organization.id},
    )

    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)

    account = await db_session.get_billing_account(organization.id)
    assert account.balance_eur == Decimal("-0.0800")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "duration, mode",
    [(0, WorkflowRunMode.WEBRTC.value), (120, WorkflowRunMode.TEXTCHAT.value)],
)
async def test_unconnected_calls_and_text_chat_are_free(
    db_session, async_session, duration, mode
):
    organization, run = await _completed_run(
        db_session, async_session, duration_seconds=duration, mode=mode
    )

    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)

    _, total = await db_session.list_billing_ledger_entries(
        organization.id, entry_type=BillingLedgerEntryType.USAGE
    )
    assert total == 0


def test_run_report_csv_includes_eur_charge(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from api.services.reports import run_report

    monkeypatch.setattr(run_report, "BILLING_PROVIDER", "stripe")
    run = SimpleNamespace(
        id=1,
        campaign_id=None,
        workflow_id=2,
        definition_id=None,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        initial_context={},
        gathered_context={},
        usage_info={"call_duration_seconds": 90},
        cost_info={"charge_eur": "0.1800"},
        public_access_token=None,
    )

    rows = run_report.build_run_report_csv([run]).getvalue().splitlines()

    header = rows[0].split(",")
    values = rows[1].split(",")
    assert values[header.index("Charge (EUR)")] == "0.1800"

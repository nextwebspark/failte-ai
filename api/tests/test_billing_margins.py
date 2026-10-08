import uuid
from decimal import Decimal

import pytest

from api.db.models import OrganizationModel, UserModel
from api.enums import WorkflowRunMode
from api.routes import billing as billing_routes
from api.services import workflow_run_billing
from api.services.auth.depends import get_superuser
from api.services.billing.margins import month_bounds, monthly_margins
from api.services.billing.provider_costs import estimate_provider_cost_eur

LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-09-2025"


def _live_usage(**overrides):
    usage = {
        "prompt_tokens": 12_000,
        "completion_tokens": 3_000,
        "total_tokens": 15_000,
        "input_audio_tokens": 10_000,
        "output_audio_tokens": 2_500,
    }
    usage.update(overrides)
    return {"llm": {f"GeminiLiveLLMService#0|||{LIVE_MODEL}": usage}}


def test_live_audio_cost_prices_audio_and_text_separately():
    # Text in 2,000 x $0.50 + audio in 10,000 x $3.00 + text out 500 x $2.00
    # + audio out 2,500 x $12.00 = $0.062, x 0.92 = EUR 0.0570.
    assert estimate_provider_cost_eur(_live_usage()) == Decimal("0.0570")


def test_unpriced_model_gives_no_estimate():
    usage = {"llm": {"OpenAILLMService#0|||gpt-4o": {"prompt_tokens": 10}}}
    assert estimate_provider_cost_eur(usage) is None


@pytest.mark.parametrize("usage_info", [None, {}, {"llm": {}}])
def test_no_llm_usage_gives_no_estimate(usage_info):
    assert estimate_provider_cost_eur(usage_info) is None


def test_month_bounds_wraps_year():
    start, end = month_bounds("2026-12")
    assert (start.year, start.month, end.year, end.month) == (2026, 12, 2027, 1)


async def _charged_run(db_session, async_session, organization, usage_info):
    user = UserModel(
        provider_id=f"margin-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    workflow = await db_session.create_workflow(
        name="Margins",
        workflow_definition={},
        user_id=user.id,
        organization_id=organization.id,
    )
    run = await db_session.create_workflow_run(
        name="margin-run",
        workflow_id=workflow.id,
        mode=WorkflowRunMode.WEBRTC.value,
        user_id=user.id,
        organization_id=organization.id,
    )
    await db_session.update_workflow_run(
        run.id, is_completed=True, usage_info=usage_info
    )
    await workflow_run_billing.report_completed_workflow_run_platform_usage(run.id)
    return await db_session.get_workflow_run_by_id(run.id)


@pytest.mark.asyncio
async def test_charge_records_cost_and_margin_and_report_aggregates(
    db_session, async_session, monkeypatch
):
    monkeypatch.setattr(workflow_run_billing, "BILLING_PROVIDER", "stripe")
    organization = OrganizationModel(
        provider_id=f"margin-org-{uuid.uuid4().hex}", name="Pub Teo"
    )
    async_session.add(organization)
    await async_session.flush()

    costed = await _charged_run(
        db_session,
        async_session,
        organization,
        {**_live_usage(), "call_duration_seconds": 120},
    )
    await _charged_run(
        db_session, async_session, organization, {"call_duration_seconds": 60}
    )

    assert costed.cost_info["charge_eur"] == "0.2400"
    assert costed.cost_info["provider_cost_eur"] == "0.0570"
    assert costed.cost_info["margin_eur"] == "0.1830"

    month = costed.created_at.strftime("%Y-%m")
    margins = {m.organization_id: m for m in await monthly_margins(month)}
    report = margins[organization.id]
    assert report.calls == 2
    assert report.billed_seconds == 180
    assert report.revenue_eur == Decimal("0.3600")
    assert report.provider_cost_eur == Decimal("0.0570")
    assert report.margin_eur == Decimal("0.1830")
    assert report.margin_percent == Decimal("76.3")
    assert report.uncosted_calls == 1


@pytest.mark.asyncio
async def test_margins_endpoint_csv(async_session, test_client_factory, monkeypatch):
    monkeypatch.setattr(billing_routes, "BILLING_PROVIDER", "stripe")
    superuser = UserModel(provider_id=f"su-{uuid.uuid4().hex}", is_superuser=True)
    async_session.add(superuser)
    await async_session.flush()

    from api.app import app

    app.dependency_overrides[get_superuser] = lambda: superuser
    try:
        async with test_client_factory(superuser) as client:
            bad = await client.get("/api/v1/superuser/billing/margins?month=2026-13")
            response = await client.get(
                "/api/v1/superuser/billing/margins?month=2026-10&format=csv"
            )
    finally:
        app.dependency_overrides.pop(get_superuser, None)

    assert bad.status_code == 422
    assert response.status_code == 200
    assert response.text.splitlines()[0].startswith("Organization ID,Organization")

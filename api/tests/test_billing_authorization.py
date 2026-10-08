from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.enums import BillingPlan
from api.services import quota_service


def _account(balance: str, credit_limit: str = "0", plan=BillingPlan.PAYG):
    return SimpleNamespace(
        plan=plan,
        balance_eur=Decimal(balance),
        credit_limit_eur=Decimal(credit_limit),
    )


@pytest.fixture
def stripe_billing(monkeypatch):
    monkeypatch.setattr(quota_service, "BILLING_PROVIDER", "stripe")
    monkeypatch.setattr(
        quota_service.db_client,
        "get_workflow",
        AsyncMock(
            return_value=SimpleNamespace(
                id=7, user_id=123, organization_id=42, workflow_configurations={}
            )
        ),
    )
    monkeypatch.setattr(
        quota_service.db_client,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(id=123, provider_id="owner")),
    )
    # The MPS path must never be consulted under Stripe billing.
    monkeypatch.setattr(
        quota_service,
        "get_effective_ai_model_configuration_for_workflow",
        AsyncMock(side_effect=AssertionError("model config must not be loaded")),
    )


def _set_account(monkeypatch, account):
    ensure = AsyncMock(return_value=account)
    monkeypatch.setattr(quota_service, "ensure_billing_account", ensure)
    return ensure


async def _authorize():
    return await quota_service.authorize_workflow_run_start(
        workflow_id=7, organization_id=42
    )


@pytest.mark.asyncio
async def test_allows_run_with_enough_credit(stripe_billing, monkeypatch):
    ensure = _set_account(monkeypatch, _account("0.50"))

    result = await _authorize()

    assert result.has_quota is True
    ensure.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_blocks_run_below_minimum_balance(stripe_billing, monkeypatch):
    _set_account(monkeypatch, _account("0.49"))

    result = await _authorize()

    assert result.has_quota is False
    assert result.error_code == "insufficient_credits"
    assert "/billing" in result.error_message


@pytest.mark.asyncio
async def test_credit_limit_lets_enterprise_go_negative(stripe_billing, monkeypatch):
    _set_account(
        monkeypatch, _account("-40", credit_limit="100", plan=BillingPlan.ENTERPRISE)
    )

    result = await _authorize()

    assert result.has_quota is True


@pytest.mark.asyncio
async def test_blocks_when_credit_limit_is_used_up(stripe_billing, monkeypatch):
    _set_account(
        monkeypatch, _account("-99.6", credit_limit="100", plan=BillingPlan.ENTERPRISE)
    )

    result = await _authorize()

    assert result.has_quota is False


@pytest.mark.asyncio
async def test_fails_closed_when_balance_cannot_be_read(stripe_billing, monkeypatch):
    monkeypatch.setattr(
        quota_service,
        "ensure_billing_account",
        AsyncMock(side_effect=RuntimeError("db down")),
    )

    result = await _authorize()

    assert result.has_quota is False
    assert result.error_code == "quota_check_failed"


@pytest.mark.asyncio
async def test_other_providers_skip_the_ledger(monkeypatch):
    monkeypatch.setattr(quota_service, "BILLING_PROVIDER", "none")
    monkeypatch.setattr(quota_service, "DEPLOYMENT_MODE", "oss")
    monkeypatch.setattr(
        quota_service.db_client,
        "get_workflow",
        AsyncMock(
            return_value=SimpleNamespace(
                id=7, user_id=123, organization_id=42, workflow_configurations={}
            )
        ),
    )
    monkeypatch.setattr(
        quota_service.db_client,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(id=123, provider_id="owner")),
    )
    monkeypatch.setattr(
        quota_service,
        "get_effective_ai_model_configuration_for_workflow",
        AsyncMock(
            return_value=SimpleNamespace(
                managed_service_version=2,
                llm=SimpleNamespace(provider="google", api_key="g-key"),
                stt=None,
                tts=None,
                embeddings=None,
            )
        ),
    )
    ensure = _set_account(monkeypatch, _account("0"))

    result = await _authorize()

    assert result.has_quota is True
    ensure.assert_not_awaited()

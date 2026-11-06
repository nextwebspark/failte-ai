"""A production API refuses to start with settings that silently fail customers."""

import pytest

from api import constants
from api.services import production_readiness as pr

READY = dict(
    email_provider="resend",
    billing_provider="stripe",
    ui_app_url="https://app.lightmove.ai",
    backend_api_endpoint="https://app.lightmove.ai",
)


def test_a_complete_production_config_has_no_problems():
    assert pr.production_config_problems(**READY) == []


@pytest.mark.parametrize(
    ("change", "mentions"),
    [
        ({"email_provider": "none"}, "EMAIL_PROVIDER"),
        ({"billing_provider": "none"}, "BILLING_PROVIDER"),
        ({"ui_app_url": "http://localhost:3010"}, "UI_APP_URL"),
        ({"ui_app_url": None}, "UI_APP_URL"),
        ({"backend_api_endpoint": "http://127.0.0.1:8000"}, "BACKEND_API_ENDPOINT"),
    ],
)
def test_each_silent_failure_is_named(change, mentions):
    [problem] = pr.production_config_problems(**{**READY, **change})
    assert mentions in problem


def test_only_production_is_checked(monkeypatch):
    monkeypatch.setattr(constants, "ENVIRONMENT", "local")
    monkeypatch.setattr(constants, "BILLING_PROVIDER", "none")
    assert pr.check_production_config({"EMAIL_PROVIDER": "none"}) == []


def test_production_refuses_to_start_and_says_why(monkeypatch):
    monkeypatch.setattr(constants, "ENVIRONMENT", "production")
    monkeypatch.setattr(constants, "BILLING_PROVIDER", "none")
    monkeypatch.setattr(constants, "UI_APP_URL", "https://app.lightmove.ai")
    monkeypatch.setattr(constants, "BACKEND_API_ENDPOINT", "https://app.lightmove.ai")
    with pytest.raises(pr.ProductionConfigError) as exc:
        pr.check_production_config({"EMAIL_PROVIDER": "resend"})
    assert "BILLING_PROVIDER" in str(exc.value)
    assert pr.OVERRIDE in str(exc.value)


def test_the_operator_can_start_anyway(monkeypatch):
    monkeypatch.setattr(constants, "ENVIRONMENT", "production")
    monkeypatch.setattr(constants, "BILLING_PROVIDER", "none")
    monkeypatch.setattr(constants, "UI_APP_URL", "https://app.lightmove.ai")
    monkeypatch.setattr(constants, "BACKEND_API_ENDPOINT", "https://app.lightmove.ai")
    problems = pr.check_production_config(
        {"EMAIL_PROVIDER": "resend", pr.OVERRIDE: "true"}
    )
    assert len(problems) == 1

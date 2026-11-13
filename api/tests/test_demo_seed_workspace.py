"""The demo seed's one-workspace mode and its live-site guard, and where
"Email me" on Reports may send."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routes.report_cards import email_me_address
from api.scripts import seed_demo_accounts as seed
from api.services.auth.permissions import Permission

STRONG = "correct-horse-battery-staple"


def _args(**overrides) -> argparse.Namespace:
    values = {"production": False, "workspace": None}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_shared_workspace_names_one_workspace_and_its_logins():
    workspace = seed.shared_workspace("LightMove Demo")
    assert workspace.slug == "lightmove-demo"
    assert workspace.name == "LightMove Demo"
    assert workspace.provider_id == "demo_lightmove_lightmove-demo"
    assert workspace.email("owner") == "lightmove-demo.owner@demo.lightmove.ai"
    assert workspace.email("staff") == "lightmove-demo.staff@demo.lightmove.ai"


def test_each_business_keeps_its_own_workspace_by_default():
    business = seed.CHMARINE
    workspace = seed.workspace_for(business)
    assert workspace.provider_id == f"demo_lightmove_{business.slug}"
    assert workspace.email("owner") == f"{business.slug}.owner@demo.lightmove.ai"


def test_shared_workspace_needs_a_name():
    with pytest.raises(SystemExit):
        seed.shared_workspace(" -- ")


def test_local_runs_need_no_opt_in(monkeypatch):
    monkeypatch.setattr(seed, "ENVIRONMENT", "local")
    assert seed.check_environment(_args(), "") is False


def test_other_environments_are_refused(monkeypatch):
    monkeypatch.setattr(seed, "ENVIRONMENT", "staging")
    with pytest.raises(SystemExit, match="ENVIRONMENT='staging'"):
        seed.check_environment(_args(production=True), STRONG)


@pytest.mark.parametrize(
    ("args", "allow", "password", "reason"),
    [
        (_args(workspace="LightMove Demo"), "yes", STRONG, "pass --production"),
        (
            _args(production=True, workspace="LightMove Demo"),
            None,
            STRONG,
            "DEMO_ALLOW_PRODUCTION=yes",
        ),
        (_args(production=True), "yes", STRONG, "--workspace"),
        (
            _args(production=True, workspace="LightMove Demo"),
            "yes",
            "short",
            "DEMO_PASSWORD",
        ),
        (
            _args(production=True, workspace="LightMove Demo"),
            "yes",
            seed.DEFAULT_PASSWORD,
            "DEMO_PASSWORD",
        ),
    ],
)
def test_the_live_site_needs_every_opt_in(monkeypatch, args, allow, password, reason):
    monkeypatch.setattr(seed, "ENVIRONMENT", "production")
    if allow is None:
        monkeypatch.delenv("DEMO_ALLOW_PRODUCTION", raising=False)
    else:
        monkeypatch.setenv("DEMO_ALLOW_PRODUCTION", allow)
    with pytest.raises(SystemExit, match=reason):
        seed.check_environment(args, password)


def test_the_live_site_runs_with_every_opt_in(monkeypatch):
    monkeypatch.setattr(seed, "ENVIRONMENT", "production")
    monkeypatch.setenv("DEMO_ALLOW_PRODUCTION", "yes")
    args = _args(production=True, workspace="LightMove Demo")
    assert seed.check_environment(args, STRONG) is True


# --- "Email me" ------------------------------------------------------------------


def _member(email: str | None, *permissions: Permission):
    return SimpleNamespace(
        user=SimpleNamespace(email=email),
        can=lambda permission: permission in permissions,
    )


def test_email_me_defaults_to_the_members_own_address():
    member = _member("niamh@example.ie", Permission.REPORTS_READ)
    assert email_me_address(member, None) == "niamh@example.ie"
    assert email_me_address(member, "  ") == "niamh@example.ie"
    assert email_me_address(member, "NIAMH@example.ie") == "niamh@example.ie"


def test_an_owner_may_send_it_to_an_address_they_type():
    owner = _member(
        "owner@demo.lightmove.ai", Permission.REPORTS_READ, Permission.REPORTS_SCHEDULE
    )
    assert email_me_address(owner, "prospect@example.com") == "prospect@example.com"


def test_staff_cannot_send_it_elsewhere():
    staff = _member("staff@example.ie", Permission.REPORTS_READ)
    with pytest.raises(HTTPException) as raised:
        email_me_address(staff, "someone@example.com")
    assert raised.value.status_code == 403


def test_no_address_at_all_is_an_error():
    with pytest.raises(HTTPException) as raised:
        email_me_address(_member(None, Permission.REPORTS_READ), None)
    assert raised.value.status_code == 422

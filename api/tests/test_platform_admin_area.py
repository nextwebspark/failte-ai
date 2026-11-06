"""The platform admin area against the test database: feature switches,
admin grants, concurrency limits, organisation and user lists, audit log."""

import uuid

import pytest
from sqlalchemy import update

from api import constants
from api.db import db_client
from api.db.models import OrganizationModel, UserModel
from api.enums import OrganizationConfigurationKey, OrgRole
from api.errors.platform_admin import LastPlatformAdminError, SelfDemotionError
from api.routes import billing as billing_routes
from api.services.auth.depends import get_superuser

ADMIN = "/api/v1/superuser/admin"


async def _org(async_session, name: str | None = None) -> OrganizationModel:
    organization = OrganizationModel(
        provider_id=f"pa-org-{uuid.uuid4().hex}", name=name or "Org"
    )
    async_session.add(organization)
    await async_session.flush()
    return organization


async def _user(
    async_session, organization=None, *, superuser: bool = False
) -> UserModel:
    user = UserModel(
        provider_id=f"pa-user-{uuid.uuid4().hex}",
        email=f"pa-{uuid.uuid4().hex}@example.com",
        selected_organization_id=organization.id if organization else None,
        is_superuser=superuser,
    )
    async_session.add(user)
    await async_session.flush()
    return user


@pytest.fixture
async def world(async_session, db_session):
    org = await _org(async_session, "Acme Dental")
    other = await _org(async_session, "Other Org")
    admin = await _user(async_session, org, superuser=True)
    member = await _user(async_session, org)
    await db_client.add_user_to_organization(member.id, org.id, role=OrgRole.ADMIN)
    return org, other, admin, member


async def test_non_admins_are_refused(world, test_client_factory):
    _, _, _, member = world
    async with test_client_factory(member) as client:
        for method, path in [
            ("GET", f"{ADMIN}/features"),
            ("GET", f"{ADMIN}/organizations"),
            ("GET", f"{ADMIN}/users"),
            ("GET", f"{ADMIN}/audit-log"),
        ]:
            response = await client.request(method, path)
            assert response.status_code == 403, path
        response = await client.put(
            f"{ADMIN}/features/campaigns", json={"enabled": True}
        )
        assert response.status_code == 403


async def test_feature_switches_platform_and_organisation(world, test_client_factory):
    org, other, admin, member = world

    async with test_client_factory(member) as client:
        assert (await client.get("/api/v1/features")).json()["features"] == {
            "campaigns": False,
            "skills": False,
        }

    async with test_client_factory(admin) as client:
        response = await client.put(
            f"{ADMIN}/features/campaigns", json={"enabled": True}
        )
        assert response.status_code == 200
        campaigns = next(
            f for f in response.json()["features"] if f["key"] == "campaigns"
        )
        assert campaigns["platform_value"] is True
        assert campaigns["effective_platform_value"] is True

        # Off for Acme only.
        response = await client.put(
            f"{ADMIN}/features/campaigns/organizations/{org.id}",
            json={"enabled": False},
        )
        assert response.status_code == 200
        # Skills on for the other organisation only.
        await client.put(
            f"{ADMIN}/features/skills/organizations/{other.id}", json={"enabled": True}
        )
        assert (
            await client.put(f"{ADMIN}/features/unknown", json={"enabled": True})
        ).status_code == 404
        assert (
            await client.put(
                f"{ADMIN}/features/skills/organizations/999999999",
                json={"enabled": True},
            )
        ).status_code == 404

    async with test_client_factory(member) as client:
        assert (await client.get("/api/v1/features")).json()["features"] == {
            "campaigns": False,
            "skills": False,
        }
        public = (await client.get("/api/v1/features/public")).json()["features"]
        assert public == {"campaigns": True, "skills": True}

    async with test_client_factory(admin) as client:
        # Removing the override puts Acme back on the platform value.
        await client.put(
            f"{ADMIN}/features/campaigns/organizations/{org.id}", json={"enabled": None}
        )
        log = (await client.get(f"{ADMIN}/audit-log?action=feature.")).json()

    async with test_client_factory(member) as client:
        assert (await client.get("/api/v1/features")).json()["features"]["campaigns"]

    actions = [
        (e["action"], e["organization_id"], e["details"]) for e in log["entries"]
    ]
    assert actions[0] == (
        "feature.organization_set",
        org.id,
        {"feature": "campaigns", "before": False, "after": None},
    )
    assert (
        "feature.platform_set",
        None,
        {"feature": "campaigns", "before": None, "after": True},
    ) in actions
    assert all(e["actor_user_id"] == admin.id for e in log["entries"])
    assert log["entries"][0]["actor_email"] == admin.email


async def test_platform_admin_grants_and_refusals(world, test_client_factory):
    _, _, admin, member = world
    async with test_client_factory(admin) as client:
        url = f"{ADMIN}/users/{member.id}/platform-admin"
        granted = await client.put(url, json={"is_platform_admin": True})
        assert granted.status_code == 200
        assert granted.json()["changed"] is True
        again = await client.put(url, json={"is_platform_admin": True})
        assert again.json()["changed"] is False

        admins = (await client.get(f"{ADMIN}/users?platform_admins_only=true")).json()
        assert {u["id"] for u in admins["users"]} >= {admin.id, member.id}

        own = await client.put(
            f"{ADMIN}/users/{admin.id}/platform-admin",
            json={"is_platform_admin": False},
        )
        assert own.status_code == 409

        revoked = await client.put(url, json={"is_platform_admin": False})
        assert revoked.status_code == 200
        assert (
            await client.put(
                f"{ADMIN}/users/999999999/platform-admin",
                json={"is_platform_admin": True},
            )
        ).status_code == 404
        log = (await client.get(f"{ADMIN}/audit-log?action=user.")).json()

    assert [e["action"] for e in log["entries"]][:2] == [
        "user.platform_admin_revoked",
        "user.platform_admin_granted",
    ]
    assert log["entries"][0]["target_user_id"] == member.id


async def test_the_last_platform_admin_cannot_be_revoked(async_session, db_session):
    # Only this test's users count (the transaction is rolled back).
    await async_session.execute(
        update(UserModel)
        .where(UserModel.is_superuser.is_(True))
        .values(is_superuser=False)
    )
    only = await _user(async_session, superuser=True)
    other = await _user(async_session)
    with pytest.raises(LastPlatformAdminError):
        await db_client.set_platform_admin(
            target_user_id=only.id, is_platform_admin=False, actor_user_id=other.id
        )
    with pytest.raises(SelfDemotionError):
        await db_client.set_platform_admin(
            target_user_id=only.id, is_platform_admin=False, actor_user_id=only.id
        )


async def test_concurrency_limit(world, test_client_factory):
    org, _, admin, _ = world
    url = f"{ADMIN}/organizations/{org.id}/concurrency-limit"
    async with test_client_factory(admin) as client:
        assert (await client.put(url, json={"limit": 0})).status_code == 422
        response = await client.put(url, json={"limit": 3})
        assert response.status_code == 200
        assert response.json()["effective_concurrency_limit"] == 3
        config = await db_client.get_configuration(
            org.id, OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value
        )
        assert config.value == {"value": 3}

        detail = (await client.get(f"{ADMIN}/organizations/{org.id}")).json()
        assert detail["organization"]["concurrency_limit"] == 3

        reset = await client.put(url, json={"limit": None})
        assert reset.json()["effective_concurrency_limit"] == (
            constants.DEFAULT_ORG_CONCURRENCY_LIMIT
        )
        assert (
            await db_client.get_configuration(
                org.id, OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value
            )
            is None
        )
        log = (await client.get(f"{ADMIN}/audit-log?organization_id={org.id}")).json()

    assert [e["details"] for e in log["entries"]][:2] == [
        {"before": 3, "after": None},
        {"before": None, "after": 3},
    ]


async def test_organisation_list_and_detail(world, test_client_factory):
    org, other, admin, member = world
    async with test_client_factory(admin) as client:
        by_email = (
            await client.get(f"{ADMIN}/organizations", params={"search": member.email})
        ).json()
        assert [o["id"] for o in by_email["organizations"]] == [org.id]
        row = by_email["organizations"][0]
        assert row["members_count"] == 1
        assert row["status"] == "active"
        assert row["last_call_at"] is None

        by_name = (
            await client.get(f"{ADMIN}/organizations", params={"search": "other org"})
        ).json()
        assert other.id in [o["id"] for o in by_name["organizations"]]
        # LIKE wildcards in the search are matched literally.
        literal = (
            await client.get(f"{ADMIN}/organizations", params={"search": "%_%"})
        ).json()
        assert org.id not in [o["id"] for o in literal["organizations"]]

        detail = await client.get(f"{ADMIN}/organizations/{org.id}")
        assert detail.status_code == 200
        body = detail.json()
        assert [(m["user_id"], m["role"]) for m in body["members"]] == [
            (member.id, "admin")
        ]
        assert body["recent_calls"] == []
        assert body["features"] == {"campaigns": False, "skills": False}
        assert (await client.get(f"{ADMIN}/organizations/999999999")).status_code == 404

        users = (
            await client.get(f"{ADMIN}/users", params={"search": member.email})
        ).json()
        assert [u["id"] for u in users["users"]] == [member.id]
        assert users["users"][0]["memberships"] == [
            {
                "organization_id": org.id,
                "organization_name": "Acme Dental",
                "role": "admin",
            }
        ]


async def test_overview_and_health(world, test_client_factory, monkeypatch):
    _, _, admin, _ = world
    monkeypatch.setattr(constants, "TOOLS_INTERNAL_SECRET", None)
    async with test_client_factory(admin) as client:
        overview = await client.get(f"{ADMIN}/overview")
        health = await client.get(f"{ADMIN}/health")
    assert overview.status_code == 200
    assert overview.json()["users_total"] >= 2
    assert overview.json()["revenue"]["month"]
    assert health.status_code == 200
    body = health.json()
    assert {c["id"] for c in body["checks"]} >= {
        "email",
        "billing",
        "public_url",
        "tools",
        "sentry",
    }
    assert body["connections"]["checked"] is False
    assert body["failed_calls_24h"] >= 0


async def test_billing_changes_are_audited(world, test_client_factory, monkeypatch):
    org, _, admin, _ = world
    monkeypatch.setattr(billing_routes, "BILLING_PROVIDER", "stripe")
    async with test_client_factory(admin) as client:
        patched = await client.patch(
            f"/api/v1/superuser/billing/organizations/{org.id}",
            json={"credit_limit_eur": "50"},
        )
        assert patched.status_code == 200
        adjusted = await client.post(
            f"/api/v1/superuser/billing/organizations/{org.id}/adjustments",
            json={
                "entry_type": "adjustment",
                "amount_eur": "10",
                "description": "Goodwill",
            },
        )
        assert adjusted.status_code == 200
        log = (await client.get(f"{ADMIN}/audit-log?action=billing.")).json()

    entries = {e["action"]: e for e in log["entries"]}
    assert entries["billing.terms_updated"]["details"]["after"] == {
        "credit_limit_eur": "50.0000"
    }
    assert entries["billing.balance_adjusted"]["details"]["reason"] == "Goodwill"
    assert entries["billing.balance_adjusted"]["organization_id"] == org.id


async def test_impersonation_is_refused_with_local_sign_in(
    world, test_client_factory, monkeypatch
):
    _, _, admin, member = world
    monkeypatch.setattr(constants, "AUTH_PROVIDER", "local")
    from api.app import app

    app.dependency_overrides[get_superuser] = lambda: admin
    try:
        async with test_client_factory(admin) as client:
            response = await client.post(
                "/api/v1/superuser/impersonate", json={"user_id": member.id}
            )
            users = (await client.get(f"{ADMIN}/users")).json()
    finally:
        app.dependency_overrides.pop(get_superuser, None)
    assert response.status_code == 501
    assert "local sign-in" in response.json()["detail"]
    assert users["impersonation_available"] is False

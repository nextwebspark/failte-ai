"""Role enforcement across the API: a coverage guard over every route, plus
representative allow/deny checks against real memberships."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.app import app
from api.db import db_client
from api.db.models import OrganizationModel, UserModel
from api.enums import OrgRole
from api.services.auth import depends as auth_depends
from api.services.auth.depends import get_org_membership, get_user

pytestmark = pytest.mark.real_org_roles

# Authenticated routes that intentionally have no organization role check:
# they act on the caller themselves, must work before an org role is known,
# or check permissions inline.
UNSCOPED_ROUTES = {
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/user/auth/user"),
    ("GET", "/api/v1/user/configurations/user"),
    ("GET", "/api/v1/user/configurations/user/validate"),
    ("GET", "/api/v1/user/onboarding-state"),
    ("PUT", "/api/v1/user/onboarding-state"),
    ("GET", "/api/v1/organizations/context"),
    ("GET", "/api/v1/organizations/telephony-config-warnings"),
    ("GET", "/api/v1/organizations/mine"),
    ("POST", "/api/v1/organizations"),
    ("POST", "/api/v1/organizations/{organization_id}/select"),
    ("POST", "/api/v1/invitations/accept"),
    ("POST", "/api/v1/superuser/impersonate"),
    ("GET", "/api/v1/superuser/workflow-runs"),
}


def _dependency_calls(dependant) -> set:
    calls = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= _dependency_calls(sub)
    return calls


def test_every_authenticated_route_checks_an_org_role():
    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = _dependency_calls(route.dependant)
        if get_user not in calls or get_org_membership in calls:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) not in UNSCOPED_ROUTES:
                missing.append(f"{method} {route.path}")
    assert not missing, (
        "Routes authenticate a user but never check their organization role. "
        "Add dependencies=requires(Permission.X), or list them in UNSCOPED_ROUTES "
        "with a reason:\n" + "\n".join(sorted(missing))
    )


# -- real memberships ---------------------------------------------------------


@pytest.fixture(scope="module")
async def sessions(setup_test_database):
    engine = create_async_engine(setup_test_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_session = db_client.engine, db_client.async_session
    db_client.engine, db_client.async_session = engine, factory
    yield factory
    db_client.engine, db_client.async_session = old_engine, old_session
    await engine.dispose()


@pytest.fixture
async def org(sessions):
    async with sessions() as session:
        organization = OrganizationModel(provider_id=f"perm-{uuid.uuid4().hex}")
        session.add(organization)
        await session.commit()

    members = {}
    for role in OrgRole:
        async with sessions() as session:
            user = UserModel(
                provider_id=f"perm-{uuid.uuid4().hex}",
                email=f"{role}-{uuid.uuid4().hex}@example.com",
                selected_organization_id=organization.id,
            )
            session.add(user)
            await session.commit()
        await db_client.add_user_to_organization(user.id, organization.id, role=role)
        members[role] = user
    return SimpleNamespace(id=organization.id, members=members)


@pytest.fixture
async def client_as(org):
    current = SimpleNamespace(user=None)

    async def _user():
        async with db_client.async_session() as session:
            return await session.scalar(
                select(UserModel).where(UserModel.id == current.user.id)
            )

    app.dependency_overrides[get_user] = _user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:

        def as_role(role: OrgRole) -> AsyncClient:
            current.user = org.members[role]
            return client

        yield as_role
    app.dependency_overrides.pop(get_user, None)


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        # Agents: everyone reads, developers+ write.
        ("GET", "/api/v1/folder/", {OrgRole.VIEWER, OrgRole.DEVELOPER, OrgRole.ADMIN}),
        ("POST", "/api/v1/folder/", {OrgRole.DEVELOPER, OrgRole.ADMIN}),
        # Telephony: hidden from viewers entirely.
        (
            "GET",
            "/api/v1/organizations/telephony-configs",
            {OrgRole.DEVELOPER, OrgRole.ADMIN},
        ),
        # API keys: developers+.
        ("GET", "/api/v1/user/api-keys", {OrgRole.DEVELOPER, OrgRole.ADMIN}),
        # Organization settings: admins only.
        ("PUT", "/api/v1/organizations/preferences", {OrgRole.ADMIN}),
        # Reports: everyone.
        (
            "GET",
            "/api/v1/organizations/reports/workflows",
            {OrgRole.VIEWER, OrgRole.DEVELOPER, OrgRole.ADMIN},
        ),
        # Team management: admins only.
        ("GET", "/api/v1/organizations/invitations", {OrgRole.ADMIN}),
    ],
)
async def test_role_matrix(client_as, method, path, allowed):
    for role in OrgRole:
        response = await client_as(role).request(
            method, path, json={"name": f"f-{uuid.uuid4().hex[:8]}"}
        )
        denied = response.status_code == 403
        assert denied is (role not in allowed), (
            f"{role} {method} {path} -> {response.status_code} {response.text[:200]}"
        )


async def test_non_member_is_rejected(sessions, client_as, org):
    outsider_org = org.members[OrgRole.ADMIN]
    async with sessions() as session:
        other = OrganizationModel(provider_id=f"perm-{uuid.uuid4().hex}")
        session.add(other)
        await session.commit()
        user = await session.scalar(
            select(UserModel).where(UserModel.id == outsider_org.id)
        )
        user.selected_organization_id = other.id
        await session.commit()

    response = await client_as(OrgRole.ADMIN).get("/api/v1/folder/")
    assert response.status_code == 403


async def test_developer_manages_only_own_api_keys(client_as, org):
    admin_key, _ = await db_client.create_api_key(
        org.id, "admin key", created_by=org.members[OrgRole.ADMIN].id
    )
    dev_key, _ = await db_client.create_api_key(
        org.id, "dev key", created_by=org.members[OrgRole.DEVELOPER].id
    )
    developer = client_as(OrgRole.DEVELOPER)

    assert (
        await developer.delete(f"/api/v1/user/api-keys/{admin_key.id}")
    ).status_code == 403
    assert (
        await developer.delete(f"/api/v1/user/api-keys/{dev_key.id}")
    ).status_code == 200

    admin = client_as(OrgRole.ADMIN)
    assert (
        await admin.put(f"/api/v1/user/api-keys/{dev_key.id}/reactivate")
    ).status_code == 200


async def test_api_key_of_viewer_is_rejected(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        auth_depends.db_client,
        "validate_api_key",
        AsyncMock(
            return_value=SimpleNamespace(
                created_by=7, organization_id=3, key_prefix="dgr_abcd"
            )
        ),
    )
    monkeypatch.setattr(
        auth_depends.db_client,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7, selected_organization_id=3)),
    )
    monkeypatch.setattr(
        auth_depends.db_client,
        "get_member_role",
        AsyncMock(return_value=OrgRole.VIEWER),
    )
    with pytest.raises(HTTPException) as exc:
        await auth_depends._handle_api_key_auth("raw-key")
    assert exc.value.status_code == 403


async def test_viewer_cannot_open_test_call_signaling(monkeypatch):
    from api.routes import webrtc_signaling

    websocket = SimpleNamespace(close=AsyncMock())
    user = SimpleNamespace(id=7, selected_organization_id=3, is_superuser=False)
    monkeypatch.setattr(
        auth_depends.db_client,
        "get_member_role",
        AsyncMock(return_value=OrgRole.VIEWER),
    )
    get_run = AsyncMock()
    monkeypatch.setattr(webrtc_signaling.db_client, "get_workflow_run", get_run)

    await webrtc_signaling.signaling_websocket(
        websocket, workflow_id=1, workflow_run_id=2, user=user
    )

    websocket.close.assert_awaited_once()
    get_run.assert_not_awaited()

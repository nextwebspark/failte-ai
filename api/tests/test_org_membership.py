"""Organization member roles: permission policy, DB membership rules, auth deps."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import db_client
from api.db.models import APIKeyModel, OrganizationModel, UserModel
from api.enums import OrgRole
from api.errors.membership import LastAdminError, MemberNotFoundError
from api.services.auth import depends as auth_depends
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    has_permissions,
)

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_every_role_has_a_permission_set():
    assert set(ROLE_PERMISSIONS) == set(OrgRole)


def test_admin_has_every_permission():
    assert ROLE_PERMISSIONS[OrgRole.ADMIN] == frozenset(Permission)


def test_roles_are_strictly_nested():
    viewer = ROLE_PERMISSIONS[OrgRole.VIEWER]
    developer = ROLE_PERMISSIONS[OrgRole.DEVELOPER]
    admin = ROLE_PERMISSIONS[OrgRole.ADMIN]
    assert viewer < developer < admin


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (OrgRole.VIEWER, Permission.CALLS_READ, True),
        (OrgRole.VIEWER, Permission.AGENTS_READ, True),
        (OrgRole.VIEWER, Permission.AGENTS_WRITE, False),
        (OrgRole.VIEWER, Permission.API_KEYS_MANAGE, False),
        (OrgRole.VIEWER, Permission.TELEPHONY_READ, False),
        (OrgRole.DEVELOPER, Permission.AGENTS_WRITE, True),
        (OrgRole.DEVELOPER, Permission.API_KEYS_MANAGE, True),
        (OrgRole.DEVELOPER, Permission.MEMBERS_MANAGE, False),
        (OrgRole.DEVELOPER, Permission.BILLING_MANAGE, False),
        (OrgRole.ADMIN, Permission.MEMBERS_MANAGE, True),
    ],
)
def test_role_grants(role, permission, allowed):
    assert has_permissions(role, permission) is allowed


# ---------------------------------------------------------------------------
# Auth dependencies (DB mocked)
# ---------------------------------------------------------------------------


def _user(*, superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=7, selected_organization_id=3, is_superuser=superuser)


async def test_org_membership_rejects_non_member(monkeypatch):
    monkeypatch.setattr(
        auth_depends.db_client, "get_member_role", AsyncMock(return_value=None)
    )
    with pytest.raises(HTTPException) as exc:
        await auth_depends.get_org_membership(_user())
    assert exc.value.status_code == 403


async def test_org_membership_superuser_acts_as_admin(monkeypatch):
    monkeypatch.setattr(
        auth_depends.db_client, "get_member_role", AsyncMock(return_value=None)
    )
    membership = await auth_depends.get_org_membership(_user(superuser=True))
    assert membership.role is OrgRole.ADMIN


async def test_require_permission_denies_missing_grant():
    check = require_permission(Permission.AGENTS_WRITE)
    viewer = OrgMembership(user=_user(), organization_id=3, role=OrgRole.VIEWER)
    with pytest.raises(HTTPException) as exc:
        await check(viewer)
    assert exc.value.status_code == 403


async def test_require_permission_returns_membership_when_granted():
    check = require_permission(Permission.AGENTS_WRITE, Permission.CALLS_READ)
    developer = OrgMembership(user=_user(), organization_id=3, role=OrgRole.DEVELOPER)
    assert await check(developer) is developer


async def test_api_key_rejected_when_creator_left_org(monkeypatch):
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
        AsyncMock(return_value=SimpleNamespace(id=7, selected_organization_id=9)),
    )
    monkeypatch.setattr(
        auth_depends.db_client, "get_member_role", AsyncMock(return_value=None)
    )
    with pytest.raises(HTTPException) as exc:
        await auth_depends._handle_api_key_auth("raw-key")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Membership DB client (real PostgreSQL)
# ---------------------------------------------------------------------------


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
async def org_with_members(sessions):
    """An org with one admin and one developer; both have it selected."""
    async with sessions() as session:
        org = OrganizationModel(provider_id=f"members-{uuid.uuid4().hex}")
        session.add(org)
        await session.flush()
        admin = UserModel(
            provider_id=f"members-{uuid.uuid4().hex}",
            email=f"admin-{uuid.uuid4().hex}@example.com",
            selected_organization_id=org.id,
        )
        developer = UserModel(
            provider_id=f"members-{uuid.uuid4().hex}",
            email=f"dev-{uuid.uuid4().hex}@example.com",
            selected_organization_id=org.id,
        )
        session.add_all([admin, developer])
        await session.commit()

    await db_client.add_user_to_organization(admin.id, org.id, role=OrgRole.ADMIN)
    await db_client.add_user_to_organization(
        developer.id, org.id, role=OrgRole.DEVELOPER, invited_by=admin.id
    )
    return SimpleNamespace(org=org, admin=admin, developer=developer)


async def test_get_member_role(org_with_members):
    data = org_with_members
    assert await db_client.get_member_role(data.admin.id, data.org.id) is OrgRole.ADMIN
    assert (
        await db_client.get_member_role(data.developer.id, data.org.id)
        is OrgRole.DEVELOPER
    )
    assert await db_client.get_member_role(data.admin.id, -1) is None


async def test_add_existing_member_keeps_role(org_with_members):
    data = org_with_members
    await db_client.add_user_to_organization(
        data.admin.id, data.org.id, role=OrgRole.VIEWER
    )
    assert await db_client.get_member_role(data.admin.id, data.org.id) is OrgRole.ADMIN


async def test_list_organization_members(org_with_members):
    data = org_with_members
    members = await db_client.list_organization_members(data.org.id)
    by_id = {m.user_id: m for m in members}
    assert by_id[data.admin.id].role is OrgRole.ADMIN
    assert by_id[data.developer.id].role is OrgRole.DEVELOPER
    assert by_id[data.developer.id].invited_by == data.admin.id
    assert by_id[data.developer.id].email == data.developer.email


async def test_list_user_organizations(org_with_members):
    data = org_with_members
    orgs = await db_client.list_user_organizations(data.developer.id)
    assert [(o.organization_id, o.role) for o in orgs] == [
        (data.org.id, OrgRole.DEVELOPER)
    ]


async def test_cannot_demote_last_admin(org_with_members):
    data = org_with_members
    with pytest.raises(LastAdminError):
        await db_client.update_member_role(data.org.id, data.admin.id, OrgRole.VIEWER)
    assert await db_client.get_member_role(data.admin.id, data.org.id) is OrgRole.ADMIN


async def test_can_demote_admin_when_another_admin_exists(org_with_members):
    data = org_with_members
    await db_client.update_member_role(data.org.id, data.developer.id, OrgRole.ADMIN)
    await db_client.update_member_role(data.org.id, data.admin.id, OrgRole.VIEWER)
    assert await db_client.get_member_role(data.admin.id, data.org.id) is OrgRole.VIEWER


async def test_update_role_of_non_member(org_with_members):
    with pytest.raises(MemberNotFoundError):
        await db_client.update_member_role(org_with_members.org.id, -1, OrgRole.VIEWER)


async def test_cannot_remove_last_admin(org_with_members):
    data = org_with_members
    with pytest.raises(LastAdminError):
        await db_client.remove_organization_member(data.org.id, data.admin.id)


async def test_remove_member_archives_keys_and_clears_selection(
    sessions, org_with_members
):
    data = org_with_members
    key, _ = await db_client.create_api_key(
        data.org.id, "dev key", created_by=data.developer.id
    )

    await db_client.remove_organization_member(data.org.id, data.developer.id)

    assert await db_client.get_member_role(data.developer.id, data.org.id) is None
    async with sessions() as session:
        stored_key = await session.scalar(
            select(APIKeyModel).where(APIKeyModel.id == key.id)
        )
        user = await session.scalar(
            select(UserModel).where(UserModel.id == data.developer.id)
        )
    assert stored_key.is_active is False
    assert stored_key.archived_at is not None
    assert user.selected_organization_id is None

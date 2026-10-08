"""Invitation lifecycle against real PostgreSQL, plus team/invitation routes."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import db_client
from api.db.models import OrganizationInvitationModel, OrganizationModel, UserModel
from api.enums import InvitationStatus, OrgRole
from api.errors.domain import DomainError
from api.errors.invitations import (
    InvitationEmailMismatchError,
    InvitationNotFoundError,
    InvitationNotUsableError,
    InvitationRateLimitError,
)
from api.errors.membership import AlreadyMemberError
from api.services.email.base import EmailDeliveryError, EmailMessage
from api.services.invitations import service as invitation_service_module
from api.services.invitations.service import INVITATION_TTL, InvitationService
from api.utils.secure_token import hash_token

pytestmark = pytest.mark.real_org_roles


@dataclass
class FakeSender:
    delivers: bool = True
    fail: bool = False
    sent: list[EmailMessage] = field(default_factory=list)

    async def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailDeliveryError("boom")
        self.sent.append(message)


@dataclass
class FakeClock:
    current: datetime = field(default_factory=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.current


def _token_from(message: EmailMessage) -> str:
    return message.text.split("/invite/", 1)[1].split()[0]


@pytest.fixture(scope="module")
async def sessions(setup_test_database):
    engine = create_async_engine(setup_test_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_session = db_client.engine, db_client.async_session
    db_client.engine, db_client.async_session = engine, factory
    yield factory
    db_client.engine, db_client.async_session = old_engine, old_session
    await engine.dispose()


async def _make_user(sessions, *, org_id: int | None = None, name: str | None = None):
    async with sessions() as session:
        user = UserModel(
            provider_id=f"inv-{uuid.uuid4().hex}",
            email=f"user-{uuid.uuid4().hex}@example.com",
            name=name,
            selected_organization_id=org_id,
        )
        session.add(user)
        await session.commit()
        return user


@pytest.fixture
async def org(sessions):
    async with sessions() as session:
        organization = OrganizationModel(
            provider_id=f"inv-{uuid.uuid4().hex}", name="Acme Marine"
        )
        session.add(organization)
        await session.commit()
    admin = await _make_user(sessions, org_id=organization.id, name="Ada Admin")
    await db_client.add_user_to_organization(
        admin.id, organization.id, role=OrgRole.ADMIN
    )
    return SimpleNamespace(id=organization.id, admin=admin)


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(sender, clock) -> InvitationService:
    return InvitationService(
        store=db_client,
        directory=db_client,
        email_sender=sender,
        clock=clock,
        app_url="https://app.example.com/",
    )


def _email() -> str:
    return f"Invitee-{uuid.uuid4().hex}@Example.com"


# -- issuing --------------------------------------------------------------------


async def test_invite_emails_link_and_stores_only_hash(sessions, org, service, sender):
    email = _email()
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.VIEWER,
    )

    assert issued.email_sent is True
    assert issued.accept_url is None
    assert issued.invitation.email == email.lower()
    [message] = sender.sent
    assert message.to == email.lower()
    assert "Acme Marine" in message.subject
    assert "Ada Admin" in message.text
    assert "Client" in message.text

    token = _token_from(message)
    async with sessions() as session:
        stored = await session.scalar(
            select(OrganizationInvitationModel).where(
                OrganizationInvitationModel.id == issued.invitation.id
            )
        )
    assert stored.token_hash == hash_token(token)
    assert token not in stored.token_hash


async def test_invite_returns_link_when_email_fails(org, service, sender):
    sender.fail = True
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=_email(),
        role=OrgRole.DEVELOPER,
    )
    assert issued.email_sent is False
    assert issued.accept_url.startswith("https://app.example.com/invite/")


async def test_invite_returns_link_when_mailer_only_logs(org, service, sender):
    sender.delivers = False
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=_email(),
        role=OrgRole.DEVELOPER,
    )
    assert issued.email_sent is False
    assert issued.accept_url is not None


async def test_invite_existing_member_rejected(org, service):
    with pytest.raises(AlreadyMemberError):
        await service.invite(
            organization_id=org.id,
            inviter_id=org.admin.id,
            email=org.admin.email.upper(),
            role=OrgRole.VIEWER,
        )


async def test_reinvite_revokes_previous_invitation(org, service, sender):
    email = _email()
    first = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.VIEWER,
    )
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.DEVELOPER,
    )

    open_invites = await service.list_open(org.id)
    assert [i.role for i in open_invites if i.email == email.lower()] == [
        OrgRole.DEVELOPER
    ]
    with pytest.raises(InvitationNotUsableError):
        await service.require_acceptable(_token_from(sender.sent[0]), email)
    assert first.invitation.id not in {i.id for i in open_invites}


async def test_invite_rate_limited(org, service, monkeypatch):
    monkeypatch.setattr(invitation_service_module, "MAX_INVITATIONS_PER_WINDOW", 1)
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=_email(),
        role=OrgRole.VIEWER,
    )
    with pytest.raises(InvitationRateLimitError):
        await service.invite(
            organization_id=org.id,
            inviter_id=org.admin.id,
            email=_email(),
            role=OrgRole.VIEWER,
        )


async def test_resend_invalidates_old_token(org, service, sender):
    email = _email()
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.VIEWER,
    )
    await service.resend(
        organization_id=org.id,
        invitation_id=issued.invitation.id,
        inviter_id=org.admin.id,
    )
    old_token, new_token = (_token_from(m) for m in sender.sent)

    with pytest.raises(InvitationNotFoundError):
        await service.preview(old_token)
    assert (await service.preview(new_token)).status is InvitationStatus.PENDING


async def test_revoke(org, service, sender):
    email = _email()
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.VIEWER,
    )
    await service.revoke(organization_id=org.id, invitation_id=issued.invitation.id)

    assert (
        await service.preview(_token_from(sender.sent[0]))
    ).status is InvitationStatus.REVOKED
    with pytest.raises(InvitationNotFoundError):
        await service.revoke(organization_id=org.id, invitation_id=issued.invitation.id)


async def test_revoke_other_org_invitation_not_found(org, service):
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=_email(),
        role=OrgRole.VIEWER,
    )
    with pytest.raises(InvitationNotFoundError):
        await service.revoke(organization_id=-1, invitation_id=issued.invitation.id)


# -- accepting ------------------------------------------------------------------


async def test_preview_shows_org_inviter_and_email(org, service, sender):
    email = _email()
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.VIEWER,
    )
    preview = await service.preview(_token_from(sender.sent[0]))
    assert preview.organization_name == "Acme Marine"
    assert preview.inviter_name == "Ada Admin"
    assert preview.role is OrgRole.VIEWER
    assert preview.email == email.lower()


async def test_accept_grants_role_selects_org_and_is_single_use(
    sessions, org, service, sender
):
    invitee = await _make_user(sessions)
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.DEVELOPER,
    )
    token = _token_from(sender.sent[0])

    await service.accept(token=token, user_id=invitee.id, email=invitee.email)

    assert await db_client.get_member_role(invitee.id, org.id) is OrgRole.DEVELOPER
    async with sessions() as session:
        user = await session.scalar(select(UserModel).where(UserModel.id == invitee.id))
    assert user.selected_organization_id == org.id
    with pytest.raises(InvitationNotUsableError):
        await service.accept(token=token, user_id=invitee.id, email=invitee.email)


async def test_accept_rejects_other_email(sessions, org, service, sender):
    invitee = await _make_user(sessions)
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=_email(),
        role=OrgRole.VIEWER,
    )
    with pytest.raises(InvitationEmailMismatchError):
        await service.accept(
            token=_token_from(sender.sent[0]), user_id=invitee.id, email=invitee.email
        )


async def test_accept_rejects_expired(sessions, org, service, sender, clock):
    invitee = await _make_user(sessions)
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.VIEWER,
    )
    clock.current += INVITATION_TTL + timedelta(seconds=1)
    with pytest.raises(InvitationNotUsableError):
        await service.accept(
            token=_token_from(sender.sent[0]), user_id=invitee.id, email=invitee.email
        )


async def test_accept_unknown_token(service):
    with pytest.raises(InvitationNotFoundError):
        await service.preview("not-a-real-token-at-all")


async def test_claim_pending_joins_every_inviting_org(sessions, org, service):
    async with sessions() as session:
        other = OrganizationModel(provider_id=f"inv-{uuid.uuid4().hex}")
        session.add(other)
        await session.commit()
    await db_client.add_user_to_organization(org.admin.id, other.id, role=OrgRole.ADMIN)
    invitee = await _make_user(sessions)
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.VIEWER,
    )
    await service.invite(
        organization_id=other.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.DEVELOPER,
    )

    claimed = await service.claim_pending(
        user_id=invitee.id, verified_email=invitee.email, select_latest=True
    )

    assert {c.organization_id for c in claimed} == {org.id, other.id}
    assert await db_client.get_member_role(invitee.id, org.id) is OrgRole.VIEWER
    assert await db_client.get_member_role(invitee.id, other.id) is OrgRole.DEVELOPER
    async with sessions() as session:
        user = await session.scalar(select(UserModel).where(UserModel.id == invitee.id))
    assert user.selected_organization_id == other.id
    # Idempotent: nothing left to claim.
    assert (
        await service.claim_pending(
            user_id=invitee.id, verified_email=invitee.email, select_latest=True
        )
        == []
    )


async def test_claim_pending_ignores_revoked_and_expired(sessions, org, service, clock):
    invitee = await _make_user(sessions)
    issued = await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.VIEWER,
    )
    await service.revoke(organization_id=org.id, invitation_id=issued.invitation.id)
    assert (
        await service.claim_pending(
            user_id=invitee.id, verified_email=invitee.email, select_latest=True
        )
        == []
    )

    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.VIEWER,
    )
    clock.current += INVITATION_TTL + timedelta(seconds=1)
    assert (
        await service.claim_pending(
            user_id=invitee.id, verified_email=invitee.email, select_latest=True
        )
        == []
    )
    assert await db_client.get_member_role(invitee.id, org.id) is None


# -- routes ---------------------------------------------------------------------


@pytest.fixture
async def team_app(sender):
    from api.app import handle_domain_error
    from api.routes.auth import router as auth_router
    from api.routes.invitations import router as invitations_router
    from api.routes.team import router as team_router
    from api.services.auth import depends as auth_depends
    from api.services.auth.account_dependencies import get_account_policy
    from api.services.auth.accounts import AccountPolicy
    from api.services.email import get_email_sender

    app = FastAPI()
    app.add_exception_handler(DomainError, handle_domain_error)
    app.include_router(team_router)
    app.include_router(invitations_router)
    app.include_router(auth_router)
    app.dependency_overrides[get_email_sender] = lambda: sender
    policy = SimpleNamespace(signup_enabled=True)
    app.dependency_overrides[get_account_policy] = lambda: AccountPolicy(
        signup_enabled=policy.signup_enabled,
        require_email_verification=True,
        app_url="https://app.example.com",
    )

    state = SimpleNamespace(user=None)

    async def _current_user():
        async with db_client.async_session() as session:
            return await session.scalar(
                select(UserModel).where(UserModel.id == state.user.id)
            )

    app.dependency_overrides[auth_depends.get_user] = _current_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(client=client, state=state, policy=policy)


async def test_admin_invites_and_viewer_cannot(sessions, org, team_app, sender):
    team_app.state.user = org.admin
    response = await team_app.client.post(
        "/organizations/invitations",
        json={"email": _email(), "role": "viewer"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["email_sent"] is True

    viewer = await _make_user(sessions, org_id=org.id)
    await db_client.add_user_to_organization(viewer.id, org.id, role=OrgRole.VIEWER)
    team_app.state.user = viewer
    response = await team_app.client.post(
        "/organizations/invitations",
        json={"email": _email(), "role": "admin"},
    )
    assert response.status_code == 403
    assert (await team_app.client.get("/organizations/members")).status_code == 200
    assert (await team_app.client.get("/organizations/invitations")).status_code == 403


async def test_invitation_request_rejects_unknown_role(org, team_app):
    team_app.state.user = org.admin
    response = await team_app.client.post(
        "/organizations/invitations",
        json={"email": _email(), "role": "owner"},
    )
    assert response.status_code == 422


async def test_last_admin_cannot_demote_self_via_route(org, team_app):
    team_app.state.user = org.admin
    response = await team_app.client.patch(
        f"/organizations/members/{org.admin.id}", json={"role": "viewer"}
    )
    assert response.status_code == 409
    assert "at least one admin" in response.json()["detail"]


async def test_admin_cannot_remove_self(org, team_app):
    team_app.state.user = org.admin
    response = await team_app.client.delete(f"/organizations/members/{org.admin.id}")
    assert response.status_code == 400


async def test_members_list_marks_current_user(org, team_app):
    team_app.state.user = org.admin
    [me] = (await team_app.client.get("/organizations/members")).json()
    assert me["is_current_user"] is True
    assert me["role"] == "admin"


async def test_select_requires_membership(sessions, org, team_app):
    outsider = await _make_user(sessions)
    team_app.state.user = outsider
    response = await team_app.client.post(f"/organizations/{org.id}/select")
    assert response.status_code == 403


async def test_signup_with_invite_joins_org_even_when_signup_disabled(
    sessions, org, service, sender, team_app, monkeypatch
):
    team_app.policy.signup_enabled = False
    email = _email()
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=email,
        role=OrgRole.VIEWER,
    )
    token = _token_from(sender.sent[0])

    response = await team_app.client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "name": "Ivy",
            "invite_token": token,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["organization_id"] == org.id
    user_id = body["user"]["id"]
    assert await db_client.get_member_role(user_id, org.id) is OrgRole.VIEWER
    assert len(await db_client.list_user_organizations(user_id)) == 1


async def test_signup_with_invite_for_other_email_creates_nothing(
    org, service, sender, team_app
):
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=_email(),
        role=OrgRole.VIEWER,
    )
    other_email = _email()
    response = await team_app.client.post(
        "/auth/signup",
        json={
            "email": other_email,
            "password": "password123",
            "invite_token": _token_from(sender.sent[0]),
        },
    )
    assert response.status_code == 403
    assert await db_client.get_user_by_email(other_email) is None


async def test_public_lookup_and_accept_route(sessions, org, service, sender, team_app):
    invitee = await _make_user(sessions)
    await service.invite(
        organization_id=org.id,
        inviter_id=org.admin.id,
        email=invitee.email,
        role=OrgRole.DEVELOPER,
    )
    token = _token_from(sender.sent[0])

    lookup = await team_app.client.get("/invitations/lookup", params={"token": token})
    assert lookup.status_code == 200
    assert lookup.json()["organization_name"] == "Acme Marine"

    team_app.state.user = invitee
    accepted = await team_app.client.post("/invitations/accept", json={"token": token})
    assert accepted.status_code == 200
    assert accepted.json() == {"organization_id": org.id}

    again = await team_app.client.post("/invitations/accept", json={"token": token})
    assert again.status_code == 410

"""Local-auth accounts: email verification, password reset, Google sign-in,
and auto-joining pending invitations. Real PostgreSQL, fake mailer/Google."""

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.app import handle_domain_error
from api.db import db_client
from api.db.models import OrganizationModel
from api.enums import OrgRole
from api.errors.domain import DomainError
from api.routes.auth import router as auth_router
from api.services.auth import depends as auth_depends
from api.services.auth.account_dependencies import get_account_policy
from api.services.auth.accounts import AccountPolicy
from api.services.auth.oauth import get_google_oauth_provider
from api.services.auth.oauth.base import AuthorizationRequest, OAuthIdentity
from api.services.email import get_email_sender
from api.services.email.base import EmailMessage
from api.services.invitations.service import InvitationService
from api.utils.auth import create_jwt_token
from api.utils.clock import SystemClock

pytestmark = pytest.mark.real_org_roles

PASSWORD = "correct horse battery"


@dataclass
class FakeSender:
    sent: list[EmailMessage] = field(default_factory=list)

    @property
    def delivers(self) -> bool:
        return True

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def link_token(self, index: int = -1) -> str:
        text = self.sent[index].text
        url = next(word for word in text.split() if "token=" in word)
        return parse_qs(urlparse(url).query)["token"][0]


@dataclass
class FakeGoogle:
    identity: OAuthIdentity | None = None
    last_request: AuthorizationRequest | None = None

    def authorization_url(self, request: AuthorizationRequest) -> str:
        self.last_request = request
        return f"https://accounts.example/auth?state={request.state}"

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> OAuthIdentity:
        assert self.last_request is not None
        assert nonce == self.last_request.nonce
        assert self.identity is not None
        return self.identity


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
async def api(sessions, monkeypatch):
    monkeypatch.setattr(auth_depends, "AUTH_PROVIDER", "local")
    # Keep org creation hermetic (no MPS / SIP provisioning).
    monkeypatch.setattr(
        "api.services.membership.ensure_organization_bootstrapped",
        _noop_bootstrap,
    )
    sender = FakeSender()
    google = FakeGoogle()
    policy = SimpleNamespace(signup_enabled=True, require_verification=True)

    app = FastAPI()
    app.add_exception_handler(DomainError, handle_domain_error)
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[get_email_sender] = lambda: sender
    app.dependency_overrides[get_google_oauth_provider] = lambda: google
    app.dependency_overrides[get_account_policy] = lambda: AccountPolicy(
        signup_enabled=policy.signup_enabled,
        require_email_verification=policy.require_verification,
        app_url="https://app.example.com",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client, sender=sender, google=google, policy=policy
        )


async def _noop_bootstrap(*_args, **_kwargs) -> bool:
    return True


def _email() -> str:
    return f"person-{uuid.uuid4().hex}@example.com"


async def _signup(api, email: str, **extra):
    return await api.client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Pat", **extra},
    )


async def _login(api, email: str, password: str = PASSWORD):
    return await api.client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


async def _make_org_with_admin(sessions) -> SimpleNamespace:
    async with sessions() as session:
        org = OrganizationModel(provider_id=f"acct-{uuid.uuid4().hex}", name="Acme")
        session.add(org)
        await session.commit()
    admin = await db_client.create_account(
        email=_email(), name="Ada", password_hash=None, email_verified_at=None
    )
    await db_client.add_user_to_organization(admin.user_id, org.id, role=OrgRole.ADMIN)
    return SimpleNamespace(id=org.id, admin_id=admin.user_id)


def _invitations(sender: FakeSender) -> InvitationService:
    return InvitationService(
        store=db_client,
        directory=db_client,
        email_sender=sender,
        clock=SystemClock(),
        app_url="https://app.example.com",
    )


# -- email verification -------------------------------------------------------


async def test_signup_requires_verification_before_login(api):
    email = _email()
    response = await _signup(api, email)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_required"] is True
    assert body["token"] is None
    assert "Verify your email" in api.sender.sent[-1].subject

    login = await _login(api, email)
    assert login.status_code == 403
    assert login.json()["code"] == "email_not_verified"

    account = await db_client.get_account_by_email(email)
    # The personal organization waits until the address is verified.
    assert await db_client.list_user_organizations(account.user_id) == []


async def test_verify_email_logs_in_creates_org_and_is_single_use(api):
    email = _email()
    await _signup(api, email)
    token = api.sender.link_token()

    verified = await api.client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text
    org_id = verified.json()["user"]["organization_id"]
    user_id = verified.json()["user"]["id"]
    assert await db_client.get_member_role(user_id, org_id) is OrgRole.ADMIN
    assert (await _login(api, email)).status_code == 200

    again = await api.client.post("/api/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400
    assert again.json()["code"] == "invalid_token"


async def test_verification_joins_pending_invites_instead_of_new_org(sessions, api):
    org = await _make_org_with_admin(sessions)
    email = _email()
    await _invitations(api.sender).invite(
        organization_id=org.id,
        inviter_id=org.admin_id,
        email=email,
        role=OrgRole.VIEWER,
    )

    await _signup(api, email)
    verified = await api.client.post(
        "/api/v1/auth/verify-email", json={"token": api.sender.link_token()}
    )

    user = verified.json()["user"]
    assert user["organization_id"] == org.id
    orgs = await db_client.list_user_organizations(user["id"])
    assert [(o.organization_id, o.role) for o in orgs] == [(org.id, OrgRole.VIEWER)]


async def test_signup_disabled_allows_address_with_pending_invite(sessions, api):
    api.policy.signup_enabled = False
    org = await _make_org_with_admin(sessions)
    invited = _email()
    await _invitations(api.sender).invite(
        organization_id=org.id,
        inviter_id=org.admin_id,
        email=invited,
        role=OrgRole.DEVELOPER,
    )

    assert (await _signup(api, invited)).status_code == 200
    rejected = await _signup(api, _email())
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "signup_disabled"


async def test_resend_verification_replaces_token_and_hides_unknown_emails(api):
    email = _email()
    await _signup(api, email)
    first = api.sender.link_token()

    unknown = await api.client.post(
        "/api/v1/auth/resend-verification", json={"email": _email()}
    )
    assert unknown.status_code == 202
    assert len(api.sender.sent) == 1

    resent = await api.client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert resent.status_code == 202
    second = api.sender.link_token()
    assert second != first

    stale = await api.client.post("/api/v1/auth/verify-email", json={"token": first})
    assert stale.status_code == 400
    fresh = await api.client.post("/api/v1/auth/verify-email", json={"token": second})
    assert fresh.status_code == 200


async def test_verification_disabled_returns_session_at_signup(api):
    api.policy.require_verification = False
    response = await _signup(api, _email())
    body = response.json()
    assert body["verification_required"] is False
    assert body["token"]
    assert body["user"]["organization_id"] is not None


async def test_jwt_of_unverified_user_is_rejected(api, monkeypatch):
    monkeypatch.setattr(auth_depends, "REQUIRE_EMAIL_VERIFICATION", True)
    email = _email()
    await _signup(api, email)
    account = await db_client.get_account_by_email(email)

    with pytest.raises(HTTPException) as exc:
        await auth_depends.get_user(
            authorization=f"Bearer {create_jwt_token(account.user_id, email)}"
        )
    assert exc.value.status_code == 403


# -- password reset -------------------------------------------------------------


async def test_password_reset_flow(api):
    api.policy.require_verification = False
    email = _email()
    await _signup(api, email)

    unknown = await api.client.post(
        "/api/v1/auth/forgot-password", json={"email": _email()}
    )
    assert unknown.status_code == 202
    sent_before = len(api.sender.sent)

    await api.client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert len(api.sender.sent) == sent_before + 1
    token = api.sender.link_token()

    too_short = await api.client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "short"}
    )
    assert too_short.status_code == 422

    reset = await api.client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "a brand new password"},
    )
    assert reset.status_code == 200
    assert (await _login(api, email)).status_code == 401
    assert (await _login(api, email, "a brand new password")).status_code == 200

    reused = await api.client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "another password"},
    )
    assert reused.status_code == 400


async def test_password_reset_verifies_email(api):
    email = _email()
    await _signup(api, email)
    await api.client.post("/api/v1/auth/forgot-password", json={"email": email})
    await api.client.post(
        "/api/v1/auth/reset-password",
        json={"token": api.sender.link_token(), "password": "a brand new password"},
    )
    assert (await _login(api, email, "a brand new password")).status_code == 200


# -- Google -------------------------------------------------------------------------


def _identity(email: str, *, sub: str | None = None, verified: bool = True):
    return OAuthIdentity(
        subject=sub or uuid.uuid4().hex,
        email=email,
        email_verified=verified,
        name="Gee User",
        picture="https://example.com/a.png",
    )


async def _google_login(api, *, state: str | None = None, **start_params):
    start = await api.client.get("/api/v1/auth/google/start", params=start_params)
    assert start.status_code == 200, start.text
    assert start.json()["authorization_url"].startswith("https://accounts.example/")
    returned_state = state or api.google.last_request.state
    return await api.client.post(
        "/api/v1/auth/google/callback",
        json={"code": "auth-code", "state": returned_state},
    )


async def test_google_creates_verified_user_with_org(api):
    email = _email()
    api.google.identity = _identity(email)

    response = await _google_login(api, next="/workflow")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"]
    assert body["next_path"] == "/workflow"
    account = await db_client.get_account_by_email(email)
    assert account.is_email_verified
    assert account.google_sub == api.google.identity.subject
    assert account.password_hash is None
    assert body["user"]["organization_id"] is not None


async def test_google_links_existing_password_account(api):
    email = _email()
    await _signup(api, email)
    existing = await db_client.get_account_by_email(email)
    api.google.identity = _identity(email)

    response = await _google_login(api)

    assert response.json()["user"]["id"] == existing.user_id
    linked = await db_client.get_account(existing.user_id)
    assert linked.google_sub == api.google.identity.subject
    # A verified Google email also verifies the password login.
    assert (await _login(api, email)).status_code == 200


async def test_google_rejects_state_mismatch(api):
    api.google.identity = _identity(_email())
    response = await _google_login(api, state="forged-state")
    assert response.status_code == 400
    assert response.json()["code"] == "oauth_failed"


async def test_google_rejects_callback_without_cookie(api):
    api.google.identity = _identity(_email())
    response = await api.client.post(
        "/api/v1/auth/google/callback", json={"code": "c", "state": "s"}
    )
    assert response.status_code == 400


async def test_google_rejects_unverified_email(api):
    api.google.identity = _identity(_email(), verified=False)
    response = await _google_login(api)
    assert response.status_code == 400


async def test_google_rejects_email_bound_to_other_google_account(api):
    email = _email()
    api.google.identity = _identity(email)
    await _google_login(api)

    api.google.identity = _identity(email)  # same email, different subject
    response = await _google_login(api)
    assert response.status_code == 400


async def test_google_with_invite_joins_org_when_signup_disabled(sessions, api):
    api.policy.signup_enabled = False
    org = await _make_org_with_admin(sessions)
    email = _email()
    await _invitations(api.sender).invite(
        organization_id=org.id,
        inviter_id=org.admin_id,
        email=email,
        role=OrgRole.DEVELOPER,
    )
    invite_token = api.sender.sent[-1].text.split("/invite/", 1)[1].split()[0]
    api.google.identity = _identity(email)

    response = await _google_login(api, invite_token=invite_token)

    assert response.status_code == 200, response.text
    user = response.json()["user"]
    assert user["organization_id"] == org.id
    assert await db_client.get_member_role(user["id"], org.id) is OrgRole.DEVELOPER


async def test_google_signup_disabled_without_invite(api):
    api.policy.signup_enabled = False
    api.google.identity = _identity(_email())
    response = await _google_login(api)
    assert response.status_code == 403


async def test_google_start_rejects_open_redirect(api):
    api.google.identity = _identity(_email())
    response = await _google_login(api, next="//evil.example/steal")
    assert response.json()["next_path"] is None


# -- OAuth building blocks ---------------------------------------------------------


def test_state_codec_rejects_tampering_and_expiry():
    from datetime import UTC, datetime, timedelta

    from api.services.auth.oauth.state import (
        STATE_TTL,
        OAuthLoginState,
        OAuthStateCodec,
    )

    codec = OAuthStateCodec("secret-a")
    value = OAuthLoginState("s", "n", "v", None, "/x")
    assert codec.decode(codec.encode(value)) == value
    assert OAuthStateCodec("secret-b").decode(codec.encode(value)) is None
    stale = codec.encode(value, now=datetime.now(UTC) - STATE_TTL - timedelta(1))
    assert codec.decode(stale) is None


def test_pkce_challenge_matches_rfc7636_example():
    from api.services.auth.oauth.pkce import code_challenge_s256

    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert (
        code_challenge_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        ({"sub": "1", "email": "a@b.co", "nonce": "wrong"}, "could not be verified"),
        ({"sub": "1", "nonce": "n"}, "no email"),
    ],
)
async def test_google_provider_validates_claims(monkeypatch, claims, message):
    from pydantic import SecretStr

    from api.errors.account import OAuthLoginError
    from api.services.auth.oauth.google import GoogleOAuthProvider

    provider = GoogleOAuthProvider(
        client_id="cid", client_secret=SecretStr("x"), redirect_uri="http://ui/cb"
    )

    async def fake_fetch(_code, _verifier):
        return "id-token"

    async def fake_verify(_token):
        return claims

    monkeypatch.setattr(provider, "_fetch_id_token", fake_fetch)
    monkeypatch.setattr(provider, "_verify_id_token", fake_verify)
    with pytest.raises(OAuthLoginError, match=message):
        await provider.exchange_code(code="c", code_verifier="v", nonce="n")


async def test_google_provider_maps_verified_identity(monkeypatch):
    from pydantic import SecretStr

    from api.services.auth.oauth.google import GoogleOAuthProvider

    provider = GoogleOAuthProvider(
        client_id="cid", client_secret=SecretStr("x"), redirect_uri="http://ui/cb"
    )

    async def fake_fetch(_code, _verifier):
        return "id-token"

    async def fake_verify(_token):
        return {
            "sub": "42",
            "email": "Mixed@Example.com",
            "email_verified": True,
            "nonce": "n",
            "name": "Gee",
        }

    monkeypatch.setattr(provider, "_fetch_id_token", fake_fetch)
    monkeypatch.setattr(provider, "_verify_id_token", fake_verify)
    identity = await provider.exchange_code(code="c", code_verifier="v", nonce="n")
    assert identity == OAuthIdentity("42", "mixed@example.com", True, "Gee", None)
    url = provider.authorization_url(AuthorizationRequest("st", "no", "ch"))
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://ui/cb"]

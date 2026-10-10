"""Catalog integrations (``/api/v1/integrations``): a proxy to the Fallcha tools
service, mocked here with respx, plus the workspace credential and MCP tool
an install creates in the (real) test database."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import constants
from api.app import app
from api.db import db_client
from api.db.models import ExternalCredentialModel, OrganizationModel, UserModel
from api.enums import OrgRole, ToolStatus
from api.errors.integrations import (
    IntegrationNotFoundError,
    ToolsServiceUnavailableError,
)
from api.services import tool_management
from api.services.auth.depends import get_user
from api.services.tool_integrations import resources as resources_module
from api.services.tool_integrations.client import Caller, ToolsServiceClient
from api.services.tool_management import ToolManagementError
from api.utils import url_security
from api.utils.trusted_origins import build_trusted_origins
from api.utils.url_security import validate_user_configured_service_url

pytestmark = pytest.mark.real_org_roles

TOOLS_URL = "http://tools.test"
SECRET = "internal-secret-for-tests-0123456789"
PROVIDER = "google-calendar"
ISSUED_KEY = "fck_live_key_must_never_leak_0001"
SA_SECRET = {"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----x"}
DISCOVERED = [{"name": "book_appointment", "description": "Book a slot"}]

CATALOG = {
    "providers": [
        {
            "id": PROVIDER,
            "title": "Google Calendar",
            "description": "Check availability and book appointments.",
            "icon": "calendar",
            "auth_modes": ["oauth2", "service_account"],
            "scopes": ["https://www.googleapis.com/auth/calendar"],
            "tools": [{"name": "book_appointment", "description": "Book a slot"}],
            "config_schema": {"type": "object"},
            "oauth": {
                "scopes": ["https://www.googleapis.com/auth/calendar"],
                "optional_scopes": [],
                "redirect_uri": "https://tools.fallcha.test/oauth/google-calendar/callback",
            },
        }
    ]
}


def _connection(connection_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": str(connection_id),
        "provider": PROVIDER,
        "auth_mode": "service_account",
        "account_label": "bot@acme.iam.gserviceaccount.com",
        "scopes_granted": [],
        "config": {"calendar_id": "c@group.calendar.google.com"},
        "status": "active",
        "last_error": None,
        "expires_at": None,
        "created_at": now,
        "updated_at": now,
        **overrides,
    }


def _install_body(**overrides: Any) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "auth_mode": "service_account",
        "secret": SA_SECRET,
        "config": {"calendar_id": "c@group.calendar.google.com"},
        **overrides,
    }


# -- fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
async def sessions(setup_test_database):
    engine = create_async_engine(setup_test_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_session = db_client.engine, db_client.async_session
    db_client.engine, db_client.async_session = engine, factory
    yield factory
    db_client.engine, db_client.async_session = old_engine, old_session
    await engine.dispose()


async def _org_with_members(sessions, roles: tuple[OrgRole, ...]) -> SimpleNamespace:
    async with sessions() as session:
        organization = OrganizationModel(provider_id=f"intg-{uuid.uuid4().hex}")
        session.add(organization)
        await session.commit()
    members = {}
    for role in roles:
        async with sessions() as session:
            user = UserModel(
                provider_id=f"intg-{uuid.uuid4().hex}",
                email=f"{role}-{uuid.uuid4().hex}@example.com",
                selected_organization_id=organization.id,
            )
            session.add(user)
            await session.commit()
        await db_client.add_user_to_organization(user.id, organization.id, role=role)
        members[role] = user
    return SimpleNamespace(id=organization.id, members=members)


@pytest.fixture
async def org(sessions) -> SimpleNamespace:
    return await _org_with_members(sessions, tuple(OrgRole))


@pytest.fixture
async def other_org(sessions) -> SimpleNamespace:
    return await _org_with_members(sessions, (OrgRole.ADMIN,))


@pytest.fixture
def configured(monkeypatch) -> None:
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", TOOLS_URL)
    monkeypatch.setattr(constants, "TOOLS_INTERNAL_SECRET", SECRET)


@pytest.fixture
def discovery(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=DISCOVERED)
    monkeypatch.setattr(tool_management, "discover_mcp_tools", mock)
    return mock


@pytest.fixture
def tools_api(configured, discovery) -> Iterator[respx.MockRouter]:
    """A stateless fake of the tools service's /internal API."""
    with respx.mock(base_url=TOOLS_URL, assert_all_called=False) as router:
        router.get("/internal/catalog", name="catalog").respond(json=CATALOG)

        def create(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                201, json=_connection(uuid.uuid4(), config=body["config"])
            )

        router.post("/internal/connections", name="create").mock(side_effect=create)

        def issue(request: httpx.Request, connection_id: str) -> httpx.Response:
            return httpx.Response(
                201,
                json={
                    "id": str(uuid.uuid4()),
                    "connection_id": connection_id,
                    "key": ISSUED_KEY,
                },
            )

        router.delete(
            path__regex=r"^/internal/connections/[0-9a-f-]+/keys/[0-9a-f-]+$",
            name="revoke_key",
        ).respond(204)

        router.post(
            path__regex=r"^/internal/connections/(?P<connection_id>[0-9a-f-]+)/keys$",
            name="issue",
        ).mock(side_effect=issue)
        router.delete(
            path__regex=r"^/internal/connections/[0-9a-f-]+$", name="revoke"
        ).respond(204)
        yield router


@pytest.fixture
async def client_as(org, other_org) -> AsyncIterator[Callable[..., AsyncClient]]:
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

        def as_member(role: OrgRole, *, organization=org) -> AsyncClient:
            current.user = organization.members[role]
            return client

        yield as_member
    app.dependency_overrides.pop(get_user, None)


async def _integration_credentials(organization_id: int, *, active_only: bool):
    credentials = await db_client.get_credentials_for_organization(
        organization_id, active_only=active_only
    )
    return [
        c
        for c in credentials
        if isinstance(c.credential_data, dict)
        and resources_module.INTEGRATION_METADATA_KEY in c.credential_data
    ]


async def _install(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/integrations/connections", json=_install_body(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- configuration --------------------------------------------------------------


async def test_catalog_is_503_until_configured(client_as, monkeypatch):
    monkeypatch.setattr(constants, "TOOLS_INTERNAL_SECRET", None)
    response = await client_as(OrgRole.ADMIN).get("/api/v1/integrations/catalog")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "tools_service_not_configured"
    assert "TOOLS_INTERNAL_SECRET" in body["detail"]


async def test_catalog_forwards_internal_identity(client_as, org, tools_api):
    response = await client_as(OrgRole.DEVELOPER).get("/api/v1/integrations/catalog")
    assert response.status_code == 200, response.text
    provider = response.json()["providers"][0]
    assert provider["id"] == PROVIDER
    assert provider["oauth"]["redirect_uri"] == (
        "https://tools.fallcha.test/oauth/google-calendar/callback"
    )

    request = tools_api["catalog"].calls.last.request
    assert request.headers["X-Internal-Secret"] == SECRET
    assert request.headers["X-Org-Id"] == str(org.id)
    assert request.headers["X-User-Id"] == str(org.members[OrgRole.DEVELOPER].id)


# -- RBAC -----------------------------------------------------------------------


FIXED_ID = uuid.uuid4()
WRITERS = {OrgRole.DEVELOPER, OrgRole.ADMIN}


@pytest.mark.parametrize(
    ("method", "path", "allowed", "success"),
    [
        ("GET", "/api/v1/integrations/catalog", WRITERS, 200),
        ("GET", "/api/v1/integrations/connections", WRITERS, 200),
        ("POST", "/api/v1/integrations/connections", WRITERS, 201),
        ("PATCH", f"/api/v1/integrations/connections/{FIXED_ID}", WRITERS, 200),
        ("POST", f"/api/v1/integrations/connections/{FIXED_ID}/test", WRITERS, 200),
        ("DELETE", f"/api/v1/integrations/connections/{FIXED_ID}", WRITERS, 204),
    ],
)
async def test_role_matrix(client_as, tools_api, method, path, allowed, success):
    tools_api.get("/internal/connections").respond(
        json={"connections": [_connection(FIXED_ID)]}
    )
    tools_api.patch(f"/internal/connections/{FIXED_ID}").respond(
        json=_connection(FIXED_ID)
    )
    tools_api.post(f"/internal/connections/{FIXED_ID}/test").respond(
        json={"ok": True, "message": "ok", "connection": _connection(FIXED_ID)}
    )
    for role in OrgRole:
        body = {"config": {}} if method == "PATCH" else _install_body()
        response = await client_as(role).request(method, path, json=body)
        expected = success if role in allowed else 403
        assert response.status_code == expected, (
            f"{role} {method} {path} -> {response.status_code} {response.text}"
        )


async def test_viewer_cannot_install(client_as, org, tools_api):
    response = await client_as(OrgRole.VIEWER).post(
        "/api/v1/integrations/connections", json=_install_body()
    )
    assert response.status_code == 403
    assert not tools_api["create"].called
    assert await _integration_credentials(org.id, active_only=False) == []


# -- install --------------------------------------------------------------------


async def test_install_creates_credential_and_mcp_tool(
    client_as, org, tools_api, discovery
):
    log_lines: list[str] = []
    sink = logger.add(log_lines.append, level="DEBUG")
    try:
        response = await client_as(OrgRole.DEVELOPER).post(
            "/api/v1/integrations/connections",
            json=_install_body(tool_name="Bookings"),
        )
    finally:
        logger.remove(sink)
    assert response.status_code == 201, response.text
    body = response.json()

    # The connection secret and the issued key never leave the server.
    assert ISSUED_KEY not in response.text
    assert SA_SECRET["private_key"] not in response.text
    logged = "\n".join(log_lines)
    assert ISSUED_KEY not in logged
    assert SA_SECRET["private_key"] not in logged

    # The secret and config were passed through to the tools service.
    sent = json.loads(tools_api["create"].calls.last.request.content)
    assert sent["secret"] == SA_SECRET
    assert sent["auth_mode"] == "service_account"
    assert sent["config"] == {"calendar_id": "c@group.calendar.google.com"}

    connection_id = body["id"]
    credential_uuid = body["credential_uuid"]
    assert body["provider"] == PROVIDER
    assert len(body["tool_uuids"]) == 1

    # The key was issued for this connection, bound to the credential.
    issue_request = tools_api["issue"].calls.last.request
    assert connection_id in issue_request.url.path
    assert json.loads(issue_request.content) == {
        "fallcha_credential_uuid": credential_uuid,
        "exclusive": True,
    }

    credential = await db_client.get_credential_by_uuid(credential_uuid, org.id)
    assert credential is not None
    assert credential.credential_type == "bearer_token"
    assert credential.credential_data["token"] == ISSUED_KEY
    assert credential.credential_data["fallcha_integration"] == {
        "provider": PROVIDER,
        "connection_id": connection_id,
    }

    tool = await db_client.get_tool_by_uuid(body["tool_uuids"][0], org.id)
    assert tool is not None
    assert tool.name == "Bookings"
    assert tool.category == "mcp"
    assert tool.icon == "calendar"
    config = tool.definition["config"]
    assert config["url"] == f"{TOOLS_URL}/mcp/{PROVIDER}"
    assert config["credential_uuid"] == credential_uuid
    assert config["discovered_tools"] == DISCOVERED
    assert discovery.await_args.kwargs["url"] == f"{TOOLS_URL}/mcp/{PROVIDER}"
    assert not tools_api["revoke"].called


async def test_install_unknown_provider_is_404(client_as, tools_api):
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=_install_body(provider="nope")
    )
    assert response.status_code == 404
    assert not tools_api["create"].called


async def test_install_rejects_oauth_and_bad_provider_ids(client_as, tools_api):
    client = client_as(OrgRole.ADMIN)
    for body in (
        _install_body(auth_mode="oauth2"),
        _install_body(provider="../internal/catalog"),
    ):
        response = await client.post("/api/v1/integrations/connections", json=body)
        assert response.status_code == 422
    assert not tools_api["catalog"].called


async def test_install_maps_tools_service_validation_error(client_as, org, tools_api):
    tools_api["create"].mock(
        return_value=httpx.Response(
            422,
            json={
                "detail": [{"loc": ["body", "secret"], "msg": "bad key", "type": "x"}]
            },
        )
    )
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=_install_body()
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "body.secret: bad key",
        "code": "integration_invalid_request",
    }
    assert await _integration_credentials(org.id, active_only=False) == []


async def test_install_rolls_back_when_key_issue_fails(client_as, org, tools_api):
    tools_api["issue"].mock(return_value=httpx.Response(500))
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=_install_body()
    )
    assert response.status_code == 502
    assert response.json()["code"] == "tools_service_unavailable"

    assert tools_api["revoke"].call_count == 1
    created = await _integration_credentials(org.id, active_only=False)
    assert len(created) == 1 and created[0].is_active is False
    assert await db_client.get_tools_for_organization(org.id, category="mcp") == []


async def test_install_rolls_back_when_tool_creation_fails(
    client_as, org, tools_api, monkeypatch
):
    monkeypatch.setattr(
        resources_module,
        "create_tool_for_user",
        AsyncMock(
            side_effect=ToolManagementError("boom", "Tool rejected", status_code=404)
        ),
    )
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=_install_body()
    )
    # The tool-management status is preserved.
    assert response.status_code == 404
    assert response.json()["detail"] == "Tool rejected"

    revoked = tools_api["revoke"].calls.last.request.url.path
    issued = tools_api["issue"].calls.last.request.url.path
    assert issued == f"{revoked}/keys"
    assert await _integration_credentials(org.id, active_only=True) == []


async def test_install_survives_failed_rollback(client_as, org, tools_api):
    tools_api["issue"].mock(return_value=httpx.Response(500))
    tools_api["revoke"].mock(side_effect=httpx.ConnectError("down"))
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=_install_body()
    )
    # The original failure is reported, and the credential is still removed.
    assert response.status_code == 502
    assert await _integration_credentials(org.id, active_only=True) == []


# -- list / update / test ---------------------------------------------------------


async def test_list_merges_installed_resources(client_as, org, tools_api):
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)
    unlinked_id = uuid.uuid4()
    tools_api.get("/internal/connections").respond(
        json={
            "connections": [
                _connection(uuid.UUID(installed["id"])),
                _connection(unlinked_id),
            ]
        }
    )

    response = await client.get("/api/v1/integrations/connections")
    assert response.status_code == 200, response.text
    by_id = {c["id"]: c for c in response.json()["connections"]}
    assert by_id[installed["id"]]["credential_uuid"] == installed["credential_uuid"]
    assert by_id[installed["id"]]["tool_uuids"] == installed["tool_uuids"]
    assert by_id[str(unlinked_id)]["credential_uuid"] is None
    assert by_id[str(unlinked_id)]["tool_uuids"] == []


async def test_update_config_and_test_are_proxied(client_as, org, tools_api):
    client = client_as(OrgRole.DEVELOPER)
    installed = await _install(client)
    connection_id = uuid.UUID(installed["id"])
    patch_route = tools_api.patch(f"/internal/connections/{connection_id}").respond(
        json=_connection(connection_id, config={"timezone": "Europe/Dublin"})
    )
    tools_api.post(f"/internal/connections/{connection_id}/test").respond(
        json={
            "ok": False,
            "message": "share the calendar with bot@acme",
            "connection": _connection(
                connection_id, status="error", last_error="not shared"
            ),
        }
    )

    response = await client.patch(
        f"/api/v1/integrations/connections/{connection_id}",
        json={"config": {"timezone": "Europe/Dublin"}},
    )
    assert response.status_code == 200, response.text
    assert json.loads(patch_route.calls.last.request.content) == {
        "config": {"timezone": "Europe/Dublin"}
    }
    assert response.json()["config"] == {"timezone": "Europe/Dublin"}
    assert response.json()["tool_uuids"] == installed["tool_uuids"]

    response = await client.post(
        f"/api/v1/integrations/connections/{connection_id}/test"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["connection"]["status"] == "error"
    assert body["connection"]["credential_uuid"] == installed["credential_uuid"]


# -- uninstall ------------------------------------------------------------------


async def test_uninstall_revokes_and_cleans_up(client_as, org, tools_api):
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)

    response = await client.delete(
        f"/api/v1/integrations/connections/{installed['id']}"
    )
    assert response.status_code == 204, response.text
    assert tools_api["revoke"].calls.last.request.url.path == (
        f"/internal/connections/{installed['id']}"
    )
    tool = await db_client.get_tool_by_uuid(
        installed["tool_uuids"][0], org.id, include_archived=True
    )
    assert tool.status == ToolStatus.ARCHIVED.value
    assert (
        await db_client.get_credential_by_uuid(installed["credential_uuid"], org.id)
        is None
    )


async def test_uninstall_unknown_connection_is_404(client_as, tools_api):
    tools_api["revoke"].mock(
        return_value=httpx.Response(404, json={"detail": "connection not found"})
    )
    response = await client_as(OrgRole.ADMIN).delete(
        f"/api/v1/integrations/connections/{uuid.uuid4()}"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "connection not found"


# -- organization scoping -------------------------------------------------------


async def test_other_org_cannot_see_or_remove_installed_resources(
    client_as, org, other_org, tools_api
):
    installed = await _install(client_as(OrgRole.ADMIN))
    connection_id = uuid.UUID(installed["id"])
    outsider = client_as(OrgRole.ADMIN, organization=other_org)

    # Even if the tools service listed the same id, org B gets none of org A's
    # credential or tools attached.
    list_route = tools_api.get("/internal/connections").respond(
        json={"connections": [_connection(connection_id)]}
    )
    response = await outsider.get("/api/v1/integrations/connections")
    assert response.status_code == 200
    assert list_route.calls.last.request.headers["X-Org-Id"] == str(other_org.id)
    [listed] = response.json()["connections"]
    assert listed["credential_uuid"] is None and listed["tool_uuids"] == []

    # The tools service scopes by X-Org-Id and answers 404 for org B.
    tools_api["revoke"].mock(
        return_value=httpx.Response(404, json={"detail": "connection not found"})
    )
    response = await outsider.delete(
        f"/api/v1/integrations/connections/{connection_id}"
    )
    assert response.status_code == 404
    revoke_request = tools_api["revoke"].calls.last.request
    assert revoke_request.headers["X-Org-Id"] == str(other_org.id)

    tool = await db_client.get_tool_by_uuid(installed["tool_uuids"][0], org.id)
    assert tool is not None and tool.status == ToolStatus.ACTIVE.value
    assert await db_client.get_credential_by_uuid(installed["credential_uuid"], org.id)


async def test_integration_metadata_is_not_exposed_by_credentials_api(
    client_as, org, tools_api
):
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)
    response = await client.get(f"/api/v1/credentials/{installed['credential_uuid']}")
    assert response.status_code == 200
    assert ISSUED_KEY not in response.text
    assert "credential_data" not in response.json()


# -- client error mapping ---------------------------------------------------------


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ToolsServiceClient:
    return ToolsServiceClient(
        base_url=TOOLS_URL,
        internal_secret=SECRET,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ToolsServiceUnavailableError),
        (500, ToolsServiceUnavailableError),
        (404, IntegrationNotFoundError),
    ],
)
async def test_client_maps_status_codes(status, error):
    client = _client(lambda _: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(error):
        await client.get_catalog(Caller(org_id=1, user_id=2))


async def test_client_maps_transport_errors_and_bad_payloads():
    def unreachable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ToolsServiceUnavailableError, match="in time"):
        await _client(unreachable).get_catalog(Caller(org_id=1, user_id=2))

    garbage = _client(lambda _: httpx.Response(200, json={"providers": "nope"}))
    with pytest.raises(ToolsServiceUnavailableError, match="unexpected"):
        await garbage.get_catalog(Caller(org_id=1, user_id=2))


async def test_issued_key_is_masked_in_repr():
    connection_id = uuid.uuid4()
    client = _client(
        lambda _: httpx.Response(
            201,
            json={
                "id": str(uuid.uuid4()),
                "connection_id": str(connection_id),
                "key": ISSUED_KEY,
            },
        )
    )
    issued = await client.issue_key(
        Caller(org_id=1, user_id=2), connection_id, fallcha_credential_uuid=None
    )
    assert ISSUED_KEY not in repr(issued)
    assert issued.key.get_secret_value() == ISSUED_KEY


# -- URL allowlist --------------------------------------------------------------


def test_trusted_origins_match_scheme_host_and_port():
    trusted = build_trusted_origins(
        ["http://fallcha-tools:8000", "https://tools.internal"],
        tools_service_url=None,
        tools_internal_secret=None,
    )
    assert trusted == {
        ("http", "fallcha-tools", 8000),
        ("https", "tools.internal", 443),
    }


def test_trusted_origins_refuse_loopback_ip_and_malformed_entries():
    trusted = build_trusted_origins(
        [
            "http://localhost:8000",
            "http://api.localhost",
            "http://127.0.0.1:8010",
            "http://169.254.169.254",
            "http://[::1]:80",
            "fallcha-tools",
            "http://ok-host:9000",
        ],
        tools_service_url=None,
        tools_internal_secret=None,
    )
    assert trusted == {("http", "ok-host", 9000)}


def test_tools_service_origin_is_trusted_only_when_configured():
    url = "http://fallcha-tools:8000"
    assert (
        build_trusted_origins([], tools_service_url=url, tools_internal_secret=None)
        == set()
    )
    assert build_trusted_origins(
        [], tools_service_url=url, tools_internal_secret=SECRET
    ) == {("http", "fallcha-tools", 8000)}
    # A loopback tools service URL is never trusted.
    assert (
        build_trusted_origins(
            [],
            tools_service_url="http://localhost:8010",
            tools_internal_secret=SECRET,
        )
        == set()
    )


def test_saas_url_guard_allows_only_trusted_origins(monkeypatch):
    monkeypatch.setattr(url_security, "DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr(
        url_security,
        "TRUSTED_ORIGINS",
        frozenset({("http", "fallcha-tools", 8000)}),
    )
    monkeypatch.setattr(
        url_security,
        "_resolve_hostname_ips",
        lambda host, port: [ipaddress.ip_address("172.18.0.5")],
    )

    validate_user_configured_service_url(
        "http://fallcha-tools:8000/v1/google-calendar/book", field_name="url"
    )
    validate_user_configured_service_url(
        "http://FALLCHA-TOOLS:8000/mcp/google-calendar", field_name="url"
    )
    for url in (
        "http://fallcha-tools:8001/x",  # another port on the same host
        "https://fallcha-tools:8000/x",  # another scheme
        "http://fallcha-tools/x",  # default port
        "http://localhost:8000/x",
        "http://10.0.0.5/x",
    ):
        with pytest.raises(ValueError):
            validate_user_configured_service_url(url, field_name="url")


async def test_credentials_without_metadata_are_ignored(org, sessions):
    """A plain bearer credential is never mistaken for an integration."""
    async with sessions() as session:
        session.add(
            ExternalCredentialModel(
                organization_id=org.id,
                created_by=org.members[OrgRole.ADMIN].id,
                name=f"plain-{uuid.uuid4().hex}",
                credential_type="bearer_token",
                credential_data={"token": "t", "fallcha_integration": {"x": 1}},
            )
        )
        await session.commit()
    resources = resources_module.DbIntegrationResources()
    assert await resources.list_linked_credentials(org.id) == []


# -- review follow-ups --------------------------------------------------------------


async def test_credentials_api_refuses_to_change_integration_credentials(
    client_as, org, tools_api
):
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)
    path = f"/api/v1/credentials/{installed['credential_uuid']}"

    response = await client.put(path, json={"credential_data": {"token": "x"}})
    assert response.status_code == 409
    assert "uninstall it from Integrations" in response.json()["detail"]
    response = await client.delete(path)
    assert response.status_code == 409

    credential = await db_client.get_credential_by_uuid(
        installed["credential_uuid"], org.id
    )
    assert credential.credential_data["token"] == ISSUED_KEY


async def test_uninstall_archives_tools_of_an_already_deleted_credential(
    client_as, org, tools_api
):
    """Orphan scenario: the credential was soft-deleted out of band (e.g.
    before the credentials API refused it); its tool must still be archived."""
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)
    await db_client.delete_credential(installed["credential_uuid"], org.id)

    response = await client.delete(
        f"/api/v1/integrations/connections/{installed['id']}"
    )
    assert response.status_code == 204
    tool = await db_client.get_tool_by_uuid(
        installed["tool_uuids"][0], org.id, include_archived=True
    )
    assert tool.status == ToolStatus.ARCHIVED.value


async def test_uninstall_cleans_up_when_tools_service_forgot_the_connection(
    client_as, org, tools_api
):
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)
    tools_api["revoke"].mock(
        return_value=httpx.Response(404, json={"detail": "connection not found"})
    )

    response = await client.delete(
        f"/api/v1/integrations/connections/{installed['id']}"
    )
    assert response.status_code == 204
    tool = await db_client.get_tool_by_uuid(
        installed["tool_uuids"][0], org.id, include_archived=True
    )
    assert tool.status == ToolStatus.ARCHIVED.value
    assert (
        await db_client.get_credential_by_uuid(installed["credential_uuid"], org.id)
        is None
    )


async def test_double_uninstall_is_safe(client_as, org, tools_api):
    client = client_as(OrgRole.ADMIN)
    installed = await _install(client)
    path = f"/api/v1/integrations/connections/{installed['id']}"

    assert (await client.delete(path)).status_code == 204
    assert (await client.delete(path)).status_code == 204
    assert tools_api["revoke"].call_count == 2
    tool = await db_client.get_tool_by_uuid(
        installed["tool_uuids"][0], org.id, include_archived=True
    )
    assert tool.status == ToolStatus.ARCHIVED.value


async def test_install_validation_errors_never_echo_the_secret(client_as, tools_api):
    client = client_as(OrgRole.ADMIN)
    for body in (
        {k: v for k, v in _install_body().items() if k != "provider"},  # input=body
        _install_body(secret=SA_SECRET["private_key"]),  # input=the secret itself
        _install_body(auth_mode="oauth2"),
    ):
        response = await client.post("/api/v1/integrations/connections", json=body)
        assert response.status_code == 422
        assert SA_SECRET["private_key"] not in response.text
        for err in response.json()["detail"]:
            assert "input" not in err and "ctx" not in err
    assert not tools_api["catalog"].called


async def test_install_rolls_back_when_cancelled(org, tools_api, monkeypatch):
    from api.schemas.integrations import InstallIntegrationRequest
    from api.services.tool_integrations import Actor, get_integration_service

    monkeypatch.setattr(
        resources_module,
        "create_tool_for_user",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    service = get_integration_service()
    with pytest.raises(asyncio.CancelledError):
        await service.install(
            Actor(organization_id=org.id, user=org.members[OrgRole.ADMIN]),
            InstallIntegrationRequest.model_validate(_install_body()),
        )
    assert tools_api["revoke"].call_count == 1
    assert await _integration_credentials(org.id, active_only=True) == []


# -- OAuth2 (bring-your-own client) -------------------------------------------------

CLIENT_SECRET = "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k"
APP_ID = uuid.uuid4()
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth?state=s&client_id=c"
REDIRECT_URI = "https://tools.example.com/oauth/google-calendar/callback"
BROWSER_NONCE = "browser-nonce-must-never-be-logged"


def _provider_app(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": str(APP_ID),
        "provider": PROVIDER,
        "client_id": "1234.apps.googleusercontent.com",
        "created_by": 1,
        "created_at": now,
        "updated_at": now,
        **overrides,
    }


def _app_body(**overrides: Any) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "client_id": "1234.apps.googleusercontent.com",
        "client_secret": CLIENT_SECRET,
        **overrides,
    }


@pytest.fixture
def oauth_api(tools_api: respx.MockRouter) -> respx.MockRouter:
    tools_api.get("/internal/provider-apps", name="list_apps").respond(
        json={"provider_apps": [_provider_app()]}
    )
    tools_api.post("/internal/provider-apps", name="create_app").respond(
        201, json=_provider_app()
    )
    tools_api.delete(
        path__regex=r"^/internal/provider-apps/[0-9a-f-]+$", name="delete_app"
    ).respond(204)
    tools_api.post("/internal/oauth/start", name="start").respond(
        json={
            "authorization_url": AUTHORIZE_URL,
            "redirect_uri": REDIRECT_URI,
            "expires_at": datetime.now(UTC).isoformat(),
            "browser_nonce": BROWSER_NONCE,
        }
    )
    tools_api.delete(
        path__regex=r"^/internal/connections/[0-9a-f-]+/keys$", name="revoke_all"
    ).respond(204)

    def confirm(request: httpx.Request, connection_id: str) -> httpx.Response:
        return httpx.Response(200, json=_oauth_connection(uuid.UUID(connection_id)))

    tools_api.post(
        path__regex=r"^/internal/connections/(?P<connection_id>[0-9a-f-]+)/confirm$",
        name="confirm",
    ).mock(side_effect=confirm)
    return tools_api


def _oauth_connection(connection_id: uuid.UUID) -> dict[str, Any]:
    return _connection(
        connection_id,
        auth_mode="oauth2",
        account_label="alice@acme.test",
        config={"calendar_id": "primary"},
    )


def _serve_connection(
    tools_api: respx.MockRouter, connection_id: uuid.UUID, **overrides: Any
) -> respx.Route:
    return tools_api.get(f"/internal/connections/{connection_id}").respond(
        json={**_oauth_connection(connection_id), **overrides}
    )


@pytest.mark.parametrize(
    ("method", "path", "body", "success"),
    [
        ("GET", "/api/v1/integrations/provider-apps", None, 200),
        ("POST", "/api/v1/integrations/provider-apps", _app_body(), 201),
        ("DELETE", f"/api/v1/integrations/provider-apps/{APP_ID}", None, 204),
        (
            "POST",
            "/api/v1/integrations/oauth/start",
            {"provider": PROVIDER, "provider_app_id": str(APP_ID)},
            200,
        ),
        ("POST", f"/api/v1/integrations/connections/{FIXED_ID}/activate", None, 200),
    ],
)
async def test_oauth_role_matrix(client_as, oauth_api, method, path, body, success):
    _serve_connection(oauth_api, FIXED_ID)
    for role in OrgRole:
        response = await client_as(role).request(method, path, json=body)
        expected = success if role in WRITERS else 403
        assert response.status_code == expected, (
            f"{role} {method} {path} -> {response.status_code} {response.text}"
        )


async def test_provider_app_secret_is_forwarded_never_returned(
    client_as, org, oauth_api
):
    log_lines: list[str] = []
    sink = logger.add(log_lines.append, level="DEBUG")
    try:
        client = client_as(OrgRole.ADMIN)
        created = await client.post(
            "/api/v1/integrations/provider-apps", json=_app_body()
        )
        listed = await client.get("/api/v1/integrations/provider-apps")
    finally:
        logger.remove(sink)
    assert created.status_code == 201, created.text
    assert created.json()["id"] == str(APP_ID)
    sent = oauth_api["create_app"].calls.last.request
    assert json.loads(sent.content) == _app_body()
    assert sent.headers["X-Org-Id"] == str(org.id)
    for text_ in (created.text, listed.text, "\n".join(log_lines)):
        assert CLIENT_SECRET not in text_
    assert listed.json()["provider_apps"][0]["client_id"].endswith(
        "googleusercontent.com"
    )


async def test_provider_app_validation_never_echoes_secret(client_as, oauth_api):
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/provider-apps",
        json=_app_body(provider="../internal", client_secret=CLIENT_SECRET * 20),
    )
    assert response.status_code == 422
    assert CLIENT_SECRET not in response.text
    assert not oauth_api["create_app"].called


async def test_provider_app_delete_conflict_is_mapped(client_as, oauth_api):
    oauth_api["delete_app"].mock(
        return_value=httpx.Response(
            409, json={"detail": "this OAuth client is used by 1 connection(s)"}
        )
    )
    response = await client_as(OrgRole.ADMIN).delete(
        f"/api/v1/integrations/provider-apps/{APP_ID}"
    )
    assert response.status_code == 409
    assert "used by 1 connection" in response.json()["detail"]


async def test_oauth_start_is_proxied(client_as, org, oauth_api):
    log_lines: list[str] = []
    sink = logger.add(log_lines.append, level="DEBUG")
    try:
        response = await client_as(OrgRole.DEVELOPER).post(
            "/api/v1/integrations/oauth/start",
            json={
                "provider": PROVIDER,
                "provider_app_id": str(APP_ID),
                "optional_scopes": ["https://www.googleapis.com/auth/gmail.send"],
                "login_hint": "alice@acme.test",
            },
        )
    finally:
        logger.remove(sink)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authorization_url"] == AUTHORIZE_URL
    assert body["redirect_uri"] == REDIRECT_URI
    # The nonce goes back to the starting user in the body, never a cookie or log.
    assert body["browser_nonce"] == BROWSER_NONCE
    assert "set-cookie" not in response.headers
    assert BROWSER_NONCE not in "\n".join(log_lines)
    request = oauth_api["start"].calls.last.request
    assert request.headers["X-Org-Id"] == str(org.id)
    assert request.headers["X-User-Id"] == str(org.members[OrgRole.DEVELOPER].id)
    assert json.loads(request.content) == {
        "provider": PROVIDER,
        "provider_app_id": str(APP_ID),
        "optional_scopes": ["https://www.googleapis.com/auth/gmail.send"],
        "login_hint": "alice@acme.test",
    }


async def test_oauth_start_unconfigured_is_503_with_reason(client_as, oauth_api):
    oauth_api["start"].mock(
        return_value=httpx.Response(
            503,
            json={"detail": "OAuth is not configured: set TOOLS_UI_RETURN_URL"},
        )
    )
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/oauth/start",
        json={"provider": PROVIDER, "provider_app_id": str(APP_ID)},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "integration_unavailable"
    # Generic: the tools service's env var names are not leaked.
    assert "TOOLS_UI_RETURN_URL" not in response.text


async def test_activate_installs_an_oauth_connection(client_as, org, oauth_api):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    response = await client_as(OrgRole.DEVELOPER).post(
        f"/api/v1/integrations/connections/{connection_id}/activate",
        json={"tool_name": "Alice's calendar"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(connection_id)
    assert body["auth_mode"] == "oauth2"
    assert ISSUED_KEY not in response.text
    assert len(body["tool_uuids"]) == 1
    assert not oauth_api["create"].called  # no new connection

    issue_request = oauth_api["issue"].calls.last.request
    assert str(connection_id) in issue_request.url.path
    assert json.loads(issue_request.content) == {
        "fallcha_credential_uuid": body["credential_uuid"],
        "exclusive": True,
    }
    credential = await db_client.get_credential_by_uuid(body["credential_uuid"], org.id)
    assert credential.credential_data["token"] == ISSUED_KEY
    tool = await db_client.get_tool_by_uuid(body["tool_uuids"][0], org.id)
    assert tool.name == "Alice's calendar"
    assert tool.definition["config"]["url"] == f"{TOOLS_URL}/mcp/{PROVIDER}"


async def test_activate_is_idempotent(client_as, org, oauth_api):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    client = client_as(OrgRole.ADMIN)
    path = f"/api/v1/integrations/connections/{connection_id}/activate"
    first = await client.post(path)
    second = await client.post(path)
    assert first.status_code == second.status_code == 200, second.text
    assert second.json()["credential_uuid"] == first.json()["credential_uuid"]
    assert second.json()["tool_uuids"] == first.json()["tool_uuids"]
    assert oauth_api["issue"].call_count == 1
    assert len(await _integration_credentials(org.id, active_only=True)) == 1


async def test_activate_other_orgs_connection_is_404(
    client_as, org, other_org, oauth_api
):
    connection_id = uuid.uuid4()
    route = oauth_api.get(f"/internal/connections/{connection_id}").respond(
        404, json={"detail": "connection not found"}
    )
    response = await client_as(OrgRole.ADMIN, organization=other_org).post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert response.status_code == 404
    assert route.calls.last.request.headers["X-Org-Id"] == str(other_org.id)
    assert not oauth_api["issue"].called
    assert await _integration_credentials(other_org.id, active_only=False) == []


async def test_activate_refuses_revoked_connection(client_as, org, oauth_api):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id, status="revoked")
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert response.status_code == 409
    assert not oauth_api["issue"].called


async def test_activate_failure_keeps_connection_and_revokes_its_key(
    client_as, org, oauth_api, monkeypatch
):
    create_tool = resources_module.create_tool_for_user
    monkeypatch.setattr(
        resources_module,
        "create_tool_for_user",
        AsyncMock(
            side_effect=ToolManagementError("boom", "Tool rejected", status_code=400)
        ),
    )
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert response.status_code == 400
    # The OAuth connection survives (activation can be retried) ...
    assert not oauth_api["revoke"].called
    # ... but the key issued for the deleted credential is revoked.
    revoked = oauth_api["revoke_key"].calls.last.request.url.path
    assert revoked.startswith(f"/internal/connections/{connection_id}/keys/")
    assert await _integration_credentials(org.id, active_only=True) == []

    # A retry succeeds (the rolled-back credential's name does not collide).
    monkeypatch.setattr(resources_module, "create_tool_for_user", create_tool)
    retry = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert retry.status_code == 200, retry.text
    assert len(retry.json()["tool_uuids"]) == 1


async def test_activate_losing_a_race_returns_the_winner(client_as, org, oauth_api):
    """The tools service refuses a second exclusive key (409): the loser
    cleans up its credential and reports the winner's install."""
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    client = client_as(OrgRole.ADMIN)
    winner = await client.post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert winner.status_code == 200

    from api.services.tool_integrations import Actor, get_integration_service
    from api.services.tool_integrations.service import _Links

    service = get_integration_service()
    original_links = service._links
    calls = {"n": 0}

    async def stale_then_fresh(organization_id: int):
        # The loser's first look predates the winner's credential.
        calls["n"] += 1
        if calls["n"] == 1:
            return _Links()
        return await original_links(organization_id)

    service._links = stale_then_fresh  # type: ignore[method-assign]
    oauth_api["issue"].mock(
        return_value=httpx.Response(
            409, json={"detail": "connection already has an active key"}
        )
    )
    result = await service.activate(
        Actor(organization_id=org.id, user=org.members[OrgRole.ADMIN]),
        connection_id,
        tool_name=None,
        browser_nonce=None,
    )
    assert result.credential_uuid == winner.json()["credential_uuid"]
    assert len(await _integration_credentials(org.id, active_only=True)) == 1


# -- review follow-ups: browser-bound confirmation and orphaned keys ----------------


async def test_activate_confirms_a_pending_connection_with_the_nonce(
    client_as, org, oauth_api
):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id, status="pending")
    log_lines: list[str] = []
    sink = logger.add(log_lines.append, level="DEBUG")
    try:
        response = await client_as(OrgRole.DEVELOPER).post(
            f"/api/v1/integrations/connections/{connection_id}/activate",
            json={"browser_nonce": BROWSER_NONCE},
        )
    finally:
        logger.remove(sink)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    confirm = oauth_api["confirm"].calls.last.request
    assert json.loads(confirm.content) == {"browser_nonce": BROWSER_NONCE}
    assert confirm.headers["X-User-Id"] == str(org.members[OrgRole.DEVELOPER].id)
    assert confirm.headers["X-Org-Id"] == str(org.id)
    assert oauth_api["issue"].called
    assert BROWSER_NONCE not in response.text
    assert BROWSER_NONCE not in "\n".join(log_lines)


@pytest.mark.parametrize("body", [None, {}, {"browser_nonce": None}])
async def test_activate_pending_without_the_nonce_is_refused(
    client_as, org, oauth_api, body
):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id, status="pending")
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate", json=body
    )
    assert response.status_code == 409
    assert "browser where you started" in response.json()["detail"]
    assert not oauth_api["confirm"].called
    assert not oauth_api["issue"].called
    assert await _integration_credentials(org.id, active_only=False) == []


async def test_activate_pending_with_a_refused_nonce(client_as, org, oauth_api):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id, status="pending")
    oauth_api["confirm"].mock(
        return_value=httpx.Response(
            409, json={"detail": "only the user who connected it can confirm it"}
        )
    )
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate",
        json={"browser_nonce": "someone-elses-nonce"},
    )
    assert response.status_code == 409
    assert not oauth_api["issue"].called
    assert await _integration_credentials(org.id, active_only=False) == []


async def test_activate_rejects_an_oversized_nonce_without_echoing_it(
    client_as, org, oauth_api
):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id, status="pending")
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate",
        json={"browser_nonce": "x" * 129},
    )
    assert response.status_code == 422
    assert "x" * 129 not in response.text
    assert not oauth_api["confirm"].called


async def test_activate_active_connection_ignores_the_nonce(client_as, org, oauth_api):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate",
        json={"browser_nonce": BROWSER_NONCE},
    )
    assert response.status_code == 200, response.text
    assert not oauth_api["confirm"].called


async def test_activate_recovers_from_orphaned_keys(client_as, org, oauth_api):
    """A live key exists but no credential holds it (an earlier rollback
    could not revoke it): revoke all keys and retry once."""
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    issued = {
        "id": str(uuid.uuid4()),
        "connection_id": str(connection_id),
        "key": ISSUED_KEY,
    }
    oauth_api["issue"].mock(
        side_effect=[
            httpx.Response(
                409, json={"detail": "connection already has an active key"}
            ),
            httpx.Response(201, json=issued),
        ]
    )
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert response.status_code == 200, response.text
    assert oauth_api["revoke_all"].calls.last.request.url.path == (
        f"/internal/connections/{connection_id}/keys"
    )
    assert oauth_api["issue"].call_count == 2
    assert len(await _integration_credentials(org.id, active_only=True)) == 1


async def test_activate_gives_up_after_one_orphan_retry(client_as, org, oauth_api):
    connection_id = uuid.uuid4()
    _serve_connection(oauth_api, connection_id)
    oauth_api["issue"].mock(
        return_value=httpx.Response(409, json={"detail": "still conflicting"})
    )
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{connection_id}/activate"
    )
    assert response.status_code == 409
    assert oauth_api["revoke_all"].call_count == 1
    assert oauth_api["issue"].call_count == 2
    assert await _integration_credentials(org.id, active_only=True) == []


# -- website catalogue sync, none auth, secret reuse -------------------------------

CATALOGUE = {
    "id": "website-catalogue",
    "title": "Website product catalogue",
    "description": "Import a shop's products.",
    "icon": "products",
    "auth_family": None,
    "auth_modes": ["none"],
    "scopes": [],
    "tools": [
        {
            "name": "search_products",
            "description": "Long agent instructions...",
            "summary": "Find products",
        }
    ],
    "config_schema": {"type": "object"},
    "oauth": None,
    "capabilities": ["sync"],
    "sync_item_label": "products",
}
SYNC_STATUS = {
    "status": "running",
    "started_at": "2026-10-10T10:00:00+00:00",
    "finished_at": None,
    "last_synced_at": None,
    "item_count": 0,
    "last_error": None,
}


@pytest.fixture
def catalogue_api(tools_api: respx.MockRouter) -> respx.MockRouter:
    tools_api["catalog"].respond(json={"providers": [*CATALOG["providers"], CATALOGUE]})
    tools_api.post(
        path__regex=r"^/internal/connections/[0-9a-f-]+/sync$", name="sync"
    ).respond(202, json=SYNC_STATUS)
    return tools_api


@pytest.mark.parametrize("role", list(OrgRole))
async def test_sync_is_proxied_for_writers(client_as, org, catalogue_api, role):
    response = await client_as(role).post(
        f"/api/v1/integrations/connections/{FIXED_ID}/sync"
    )
    if role not in WRITERS:
        assert response.status_code == 403
        assert not catalogue_api["sync"].called
        return
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"
    request = catalogue_api["sync"].calls.last.request
    assert request.url.path == f"/internal/connections/{FIXED_ID}/sync"
    assert request.headers["X-Org-Id"] == str(org.id)


@pytest.mark.parametrize(("status", "expected"), [(409, 409), (404, 404), (422, 422)])
async def test_sync_errors_are_mapped(client_as, catalogue_api, status, expected):
    catalogue_api["sync"].mock(
        return_value=httpx.Response(
            status, json={"detail": "a sync is already running for this connection"}
        )
    )
    response = await client_as(OrgRole.ADMIN).post(
        f"/api/v1/integrations/connections/{FIXED_ID}/sync"
    )
    assert response.status_code == expected
    if status == 409:
        assert "already running" in response.json()["detail"]


async def test_catalog_and_connections_carry_sync_metadata(client_as, catalogue_api):
    client = client_as(OrgRole.DEVELOPER)
    catalog = await client.get("/api/v1/integrations/catalog")
    entry = {p["id"]: p for p in catalog.json()["providers"]}["website-catalogue"]
    assert entry["capabilities"] == ["sync"]
    assert entry["sync_item_label"] == "products"
    assert entry["tools"][0]["summary"] == "Find products"
    catalogue_api.get("/internal/connections").respond(
        json={
            "connections": [
                _connection(
                    FIXED_ID,
                    provider="website-catalogue",
                    auth_mode="none",
                    sync={**SYNC_STATUS, "status": "succeeded", "item_count": 42},
                )
            ]
        }
    )
    listed = await client.get("/api/v1/integrations/connections")
    assert listed.json()["connections"][0]["sync"]["item_count"] == 42


async def test_install_without_a_secret_for_none_auth(client_as, catalogue_api):
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections",
        json={
            "provider": "website-catalogue",
            "auth_mode": "none",
            "config": {"site_url": "https://shop.example.com"},
        },
    )
    assert response.status_code == 201, response.text
    sent = json.loads(catalogue_api["create"].calls.last.request.content)
    assert sent["auth_mode"] == "none" and sent["secret"] == {}
    assert "reuse_secret_from" not in sent


async def test_install_reusing_a_secret(client_as, tools_api):
    source = uuid.uuid4()
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections",
        json=_install_body(secret={}, reuse_secret_from=str(source)),
    )
    assert response.status_code == 201, response.text
    sent = json.loads(tools_api["create"].calls.last.request.content)
    assert sent["reuse_secret_from"] == str(source) and sent["secret"] == {}


@pytest.mark.parametrize(
    "body",
    [
        _install_body(secret={}),  # neither
        _install_body(reuse_secret_from=str(uuid.uuid4())),  # both
        _install_body(auth_mode="none"),  # none with a secret
        _install_body(auth_mode="none", secret={}, reuse_secret_from=str(FIXED_ID)),
    ],
)
async def test_install_secret_source_is_validated(client_as, tools_api, body):
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=body
    )
    assert response.status_code == 422
    assert not tools_api["create"].called
    assert "private_key" not in response.text


async def test_reuse_refusals_are_mapped(client_as, tools_api):
    tools_api["create"].mock(
        return_value=httpx.Response(
            422,
            json={
                "detail": "only connections of the same provider family can share a secret"
            },
        )
    )
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections",
        json=_install_body(secret={}, reuse_secret_from=str(uuid.uuid4())),
    )
    assert response.status_code == 422
    assert "same provider family" in response.json()["detail"]

"""Catalog integrations (``/api/v1/integrations``): a proxy to the Fallcha tools
service, mocked here with respx, plus the workspace credential and MCP tool
an install creates in the (real) test database."""

from __future__ import annotations

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
            "auth_modes": ["service_account"],
            "scopes": ["https://www.googleapis.com/auth/calendar"],
            "tools": [{"name": "book_appointment", "description": "Book a slot"}],
            "config_schema": {"type": "object"},
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
    assert response.json()["providers"][0]["id"] == PROVIDER

    request = tools_api["catalog"].calls.last.request
    assert request.headers["X-Internal-Secret"] == SECRET
    assert request.headers["X-Org-Id"] == str(org.id)
    assert request.headers["X-User-Id"] == str(org.members[OrgRole.DEVELOPER].id)


# -- RBAC -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("GET", "/api/v1/integrations/catalog", {OrgRole.DEVELOPER, OrgRole.ADMIN}),
        ("GET", "/api/v1/integrations/connections", {OrgRole.DEVELOPER, OrgRole.ADMIN}),
        (
            "POST",
            "/api/v1/integrations/connections",
            {OrgRole.DEVELOPER, OrgRole.ADMIN},
        ),
        (
            "PATCH",
            f"/api/v1/integrations/connections/{uuid.uuid4()}",
            {OrgRole.DEVELOPER, OrgRole.ADMIN},
        ),
        (
            "POST",
            f"/api/v1/integrations/connections/{uuid.uuid4()}/test",
            {OrgRole.DEVELOPER, OrgRole.ADMIN},
        ),
        (
            "DELETE",
            f"/api/v1/integrations/connections/{uuid.uuid4()}",
            {OrgRole.DEVELOPER, OrgRole.ADMIN},
        ),
    ],
)
async def test_role_matrix(client_as, configured, method, path, allowed):
    # Unmatched calls to the fake fail loudly; only denial is asserted here.
    with respx.mock(base_url=TOOLS_URL, assert_all_called=False) as router:
        router.route().respond(404, json={"detail": "connection not found"})
        for role in OrgRole:
            body = {"config": {}} if method == "PATCH" else _install_body()
            response = await client_as(role).request(method, path, json=body)
            denied = response.status_code == 403
            assert denied is (role not in allowed), (
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
        "fallcha_credential_uuid": credential_uuid
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
        AsyncMock(side_effect=ToolManagementError("boom", "Tool rejected")),
    )
    response = await client_as(OrgRole.ADMIN).post(
        "/api/v1/integrations/connections", json=_install_body()
    )
    assert response.status_code == 422
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
        transport=httpx.MockTransport(handler),
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


def test_tools_service_host_is_trusted_by_default():
    host = httpx.URL(constants.TOOLS_SERVICE_URL).host
    assert host in constants.TRUSTED_TOOL_HOSTS


def test_saas_url_guard_allows_only_trusted_internal_hosts(monkeypatch):
    monkeypatch.setattr(url_security, "DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr(
        url_security, "TRUSTED_TOOL_HOSTS", frozenset({"fallcha-tools"})
    )

    validate_user_configured_service_url(
        "http://fallcha-tools:8000/v1/google-calendar/book", field_name="url"
    )
    validate_user_configured_service_url(
        "http://FALLCHA-TOOLS:8000/mcp/google-calendar", field_name="url"
    )
    for url in ("http://localhost:8000/x", "http://10.0.0.5/x"):
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

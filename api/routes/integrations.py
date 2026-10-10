"""Catalog integrations: providers hosted by the Fallcha tools service.

A thin, RBAC-enforcing proxy. Reads need ``INTEGRATIONS_READ``; connecting
(including OAuth clients and starting an OAuth flow), reconfiguring, testing
and removing need ``INTEGRATIONS_WRITE`` (installing, activating and
uninstalling also create/archive a tool, so they need ``AGENTS_WRITE`` too).

OAuth2 (bring-your-own client): save the workspace's OAuth client
(``POST /provider-apps``), start the flow (``POST /oauth/start``) and send
the browser to the returned URL. The provider redirects to the tools
service, which creates the connection and sends the browser back to the UI
with ``connection_id``; then ``POST /connections/{id}/activate`` (with the
``browser_nonce`` from ``oauth/start``) confirms and installs it.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from api.schemas.integrations import (
    ActivateIntegrationRequest,
    CreateProviderAppRequest,
    InstallIntegrationRequest,
    IntegrationCatalogResponse,
    IntegrationConnectionListResponse,
    IntegrationConnectionResponse,
    IntegrationTestResponse,
    ProviderAppListResponse,
    ProviderAppResponse,
    StartOAuthRequest,
    StartOAuthResponse,
    UpdateIntegrationConfigRequest,
)
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.tool_integrations import (
    Actor,
    IntegrationService,
    get_integration_service,
)


class _NoEchoValidationRoute(APIRoute):
    """422s without each error's ``input``/``ctx``: install bodies carry
    provider secrets, which FastAPI would otherwise echo back."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def no_echo_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise RequestValidationError(
                    [
                        {k: v for k, v in err.items() if k not in ("input", "ctx")}
                        for err in exc.errors()
                    ]
                ) from None

        return no_echo_handler


router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
    route_class=_NoEchoValidationRoute,
)

Integrations = Annotated[IntegrationService, Depends(get_integration_service)]

Reader = Annotated[
    OrgMembership, Depends(require_permission(Permission.INTEGRATIONS_READ))
]
Writer = Annotated[
    OrgMembership, Depends(require_permission(Permission.INTEGRATIONS_WRITE))
]
Installer = Annotated[
    OrgMembership,
    Depends(require_permission(Permission.INTEGRATIONS_WRITE, Permission.AGENTS_WRITE)),
]


def _actor(membership: OrgMembership) -> Actor:
    return Actor(organization_id=membership.organization_id, user=membership.user)


@router.get("/catalog")
async def get_catalog(
    membership: Reader, integrations: Integrations
) -> IntegrationCatalogResponse:
    """Providers available to every workspace."""
    return await integrations.catalog(_actor(membership))


@router.get("/connections")
async def list_connections(
    membership: Reader, integrations: Integrations
) -> IntegrationConnectionListResponse:
    """This workspace's connections, with the credential and tools installed
    for each."""
    connections = await integrations.list_connections(_actor(membership))
    return IntegrationConnectionListResponse(connections=connections)


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def install_integration(
    request: InstallIntegrationRequest,
    membership: Installer,
    integrations: Integrations,
) -> IntegrationConnectionResponse:
    """Connect a provider and install it as an MCP tool."""
    return await integrations.install(_actor(membership), request)


@router.post("/connections/{connection_id}/activate")
async def activate_connection(
    connection_id: uuid.UUID,
    membership: Installer,
    integrations: Integrations,
    request: ActivateIntegrationRequest | None = None,
) -> IntegrationConnectionResponse:
    """Install an existing connection (e.g. one the OAuth flow just created)
    as an MCP tool. Returns the existing install if it is already active.

    A just-authorized OAuth connection is pending: it is confirmed only for
    the user who started the flow, with the ``browser_nonce`` that
    ``POST /oauth/start`` returned to them."""
    nonce = request.browser_nonce if request else None
    return await integrations.activate(
        _actor(membership),
        connection_id,
        tool_name=request.tool_name if request else None,
        browser_nonce=nonce.get_secret_value() if nonce else None,
    )


@router.patch("/connections/{connection_id}")
async def update_connection_config(
    connection_id: uuid.UUID,
    request: UpdateIntegrationConfigRequest,
    membership: Writer,
    integrations: Integrations,
) -> IntegrationConnectionResponse:
    """Merge non-secret settings into the connection's config."""
    return await integrations.update_config(
        _actor(membership), connection_id, request.config
    )


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: uuid.UUID,
    membership: Writer,
    integrations: Integrations,
) -> IntegrationTestResponse:
    """Check the connection against the provider and record its status."""
    return await integrations.test(_actor(membership), connection_id)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_integration(
    connection_id: uuid.UUID,
    membership: Installer,
    integrations: Integrations,
) -> Response:
    """Revoke the connection, archive its tools and delete its credential."""
    await integrations.uninstall(_actor(membership), connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- OAuth2 (bring-your-own client) ---------------------------------------------


@router.get("/provider-apps")
async def list_provider_apps(
    membership: Reader, integrations: Integrations
) -> ProviderAppListResponse:
    """This workspace's OAuth clients. Secrets are never returned."""
    return await integrations.list_provider_apps(_actor(membership))


@router.post("/provider-apps", status_code=status.HTTP_201_CREATED)
async def create_provider_app(
    request: CreateProviderAppRequest,
    membership: Writer,
    integrations: Integrations,
) -> ProviderAppResponse:
    """Save the workspace's own OAuth client (from its Google Cloud project)."""
    return await integrations.create_provider_app(_actor(membership), request)


@router.delete("/provider-apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_app(
    app_id: uuid.UUID,
    membership: Writer,
    integrations: Integrations,
) -> Response:
    """Remove an OAuth client; refused (409) while a connection uses it."""
    await integrations.delete_provider_app(_actor(membership), app_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/oauth/start")
async def start_oauth(
    request: StartOAuthRequest,
    membership: Writer,
    integrations: Integrations,
) -> StartOAuthResponse:
    """Start an OAuth2 authorization: send the browser to
    ``authorization_url``. ``redirect_uri`` must be registered on the OAuth
    client. Keep ``browser_nonce`` in this browser and send it to
    ``activate`` when the provider redirects back."""
    started = await integrations.start_oauth(_actor(membership), request)
    return StartOAuthResponse(
        authorization_url=started.authorization_url,
        redirect_uri=started.redirect_uri,
        expires_at=started.expires_at,
        browser_nonce=started.browser_nonce.get_secret_value(),
    )

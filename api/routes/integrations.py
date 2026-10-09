"""Catalog integrations: providers hosted by the Fallcha tools service.

A thin, RBAC-enforcing proxy. Reads need ``INTEGRATIONS_READ``; connecting,
reconfiguring, testing and removing need ``INTEGRATIONS_WRITE`` (installing
and uninstalling also create/archive a tool, so they need ``AGENTS_WRITE``
too).
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from api.schemas.integrations import (
    InstallIntegrationRequest,
    IntegrationCatalogResponse,
    IntegrationConnectionListResponse,
    IntegrationConnectionResponse,
    IntegrationTestResponse,
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

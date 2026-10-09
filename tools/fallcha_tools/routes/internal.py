"""``/internal/*``: called by the Fallcha API on behalf of a workspace user."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from loguru import logger

from fallcha_tools.core.auth import InternalCallerDep, require_internal_caller
from fallcha_tools.core.container import ConnectionRepoDep, KeyRepoDep, ServicesDep
from fallcha_tools.core.errors import InvalidRequestError
from fallcha_tools.core.models import AuthMode, ConnectionStatus
from fallcha_tools.core.provider import ConnectionContext, ConnectionTestResult
from fallcha_tools.core.repositories import ConnectionInfo
from fallcha_tools.schemas import (
    CatalogProvider,
    CatalogResponse,
    ConnectionList,
    ConnectionOut,
    ConnectionTestOut,
    CreateConnectionRequest,
    IssuedKeyOut,
    IssueKeyRequest,
    ToolSummary,
)

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_caller)])

# OAuth2 connections are created by the OAuth callback, never from raw input.
_DIRECT_AUTH_MODES = frozenset({AuthMode.SERVICE_ACCOUNT, AuthMode.API_KEY})
_TEST_FAILED = "connection test failed unexpectedly"


def _out(info: ConnectionInfo) -> ConnectionOut:
    return ConnectionOut.model_validate(info)


@router.get("/catalog")
async def get_catalog(services: ServicesDep) -> CatalogResponse:
    providers = []
    for provider in services.registry:
        tools = await services.mcp.tool_summaries(provider.id)
        providers.append(
            CatalogProvider(
                id=provider.id,
                title=provider.title,
                description=provider.description,
                icon=provider.icon,
                auth_modes=sorted(provider.auth_modes),
                scopes=list(provider.scopes),
                tools=[ToolSummary(name=n, description=d) for n, d in tools],
            )
        )
    return CatalogResponse(providers=providers)


@router.get("/connections")
async def list_connections(
    caller: InternalCallerDep,
    repo: ConnectionRepoDep,
    include_revoked: bool = False,
) -> ConnectionList:
    rows = await repo.list_connections(caller.org_id, include_revoked=include_revoked)
    return ConnectionList(connections=[_out(row) for row in rows])


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: CreateConnectionRequest,
    caller: InternalCallerDep,
    services: ServicesDep,
    repo: ConnectionRepoDep,
) -> ConnectionOut:
    provider = services.registry.get(body.provider)
    if body.auth_mode not in _DIRECT_AUTH_MODES:
        raise InvalidRequestError(
            f"{body.auth_mode} connections cannot be created here"
        )
    if body.auth_mode not in provider.auth_modes:
        raise InvalidRequestError(
            f"provider {provider.id!r} does not support {body.auth_mode}"
        )
    info = await repo.create_connection(
        org_id=caller.org_id,
        provider=provider.id,
        auth_mode=body.auth_mode,
        secret=body.secret,
        account_label=body.account_label,
        scopes_granted=tuple(body.scopes_granted),
        created_by=caller.user_id,
    )
    return _out(info)


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: uuid.UUID, caller: InternalCallerDep, repo: ConnectionRepoDep
) -> ConnectionOut:
    return _out(await repo.get_connection(caller.org_id, connection_id))


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: uuid.UUID,
    caller: InternalCallerDep,
    services: ServicesDep,
    repo: ConnectionRepoDep,
) -> ConnectionTestOut:
    loaded = await repo.load_secrets(caller.org_id, connection_id)
    provider = services.registry.get(loaded.info.provider)
    ctx = ConnectionContext(
        org_id=caller.org_id,
        connection_id=connection_id,
        provider=provider.id,
        auth_mode=loaded.info.auth_mode,
        secret=loaded.secret,
        access_token=loaded.access_token,
        http=services.http,
    )
    try:
        result = await provider.test_connection(ctx)
    except Exception as exc:  # a provider bug must not become a 500
        # Type only: the message or locals could contain secret material.
        logger.warning(
            "connection test for {} ({}) raised {}",
            connection_id,
            provider.id,
            type(exc).__name__,
        )
        result = ConnectionTestResult(ok=False, message=_TEST_FAILED)
    info = await repo.set_status(
        caller.org_id,
        connection_id,
        ConnectionStatus.ACTIVE if result.ok else ConnectionStatus.ERROR,
        last_error=None if result.ok else result.message,
        account_label=result.account_label,
    )
    return ConnectionTestOut(
        ok=result.ok, message=result.message, connection=_out(info)
    )


@router.post("/connections/{connection_id}/keys", status_code=status.HTTP_201_CREATED)
async def issue_key(
    connection_id: uuid.UUID,
    caller: InternalCallerDep,
    keys: KeyRepoDep,
    body: IssueKeyRequest | None = None,
) -> IssuedKeyOut:
    issued = await keys.issue_key(
        org_id=caller.org_id,
        connection_id=connection_id,
        fallcha_credential_uuid=body.fallcha_credential_uuid if body else None,
        created_by=caller.user_id,
    )
    return IssuedKeyOut(
        id=issued.id, connection_id=issued.connection_id, key=issued.key
    )


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connection(
    connection_id: uuid.UUID, caller: InternalCallerDep, repo: ConnectionRepoDep
) -> Response:
    await repo.revoke_connection(caller.org_id, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

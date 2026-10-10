"""``/internal/*``: called by the Fallcha API on behalf of a workspace user."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from fastapi import APIRouter, Depends, Response, status
from loguru import logger
from pydantic import JsonValue, ValidationError

from fallcha_tools.core.auth import InternalCallerDep, require_internal_caller
from fallcha_tools.core.container import (
    AppServices,
    ConnectionRepoDep,
    KeyRepoDep,
    ServicesDep,
)
from fallcha_tools.core.errors import InvalidRequestError, describe_validation_error
from fallcha_tools.core.models import AuthMode, ConnectionStatus
from fallcha_tools.core.provider import (
    ConnectionTestResult,
    Provider,
    SyncableProvider,
    provider_capabilities,
)
from fallcha_tools.core.repositories import ConnectionInfo
from fallcha_tools.core.sync import SyncInfo, SyncRepository
from fallcha_tools.schemas import (
    CatalogOAuth,
    CatalogProvider,
    CatalogResponse,
    ConnectionList,
    ConnectionOut,
    ConnectionTestOut,
    CreateConnectionRequest,
    IssuedKeyOut,
    IssueKeyRequest,
    SyncStatusOut,
    ToolSummary,
    UpdateConnectionRequest,
)

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_caller)])

# OAuth2 connections are created by the OAuth callback, never from raw input.
_DIRECT_AUTH_MODES = frozenset(
    {AuthMode.SERVICE_ACCOUNT, AuthMode.API_KEY, AuthMode.NONE}
)
_TEST_FAILED = "connection test failed unexpectedly"


def _out(info: ConnectionInfo, sync: SyncInfo | None = None) -> ConnectionOut:
    out = ConnectionOut.model_validate(info)
    if sync is not None:
        out.sync = SyncStatusOut.model_validate(sync)
    return out


async def _outs(
    services: AppServices, org_id: int, infos: Sequence[ConnectionInfo]
) -> list[ConnectionOut]:
    """Connections with their latest sync status attached."""
    async with services.db.session() as session:
        syncs = await SyncRepository(session, services.sync.clock).get_many(
            org_id, (info.id for info in infos)
        )
    return [_out(info, syncs.get(info.id)) for info in infos]


async def _one(
    services: AppServices, org_id: int, info: ConnectionInfo
) -> ConnectionOut:
    [out] = await _outs(services, org_id, [info])
    return out


def _default_account_label(
    auth_mode: AuthMode, secret: Mapping[str, JsonValue]
) -> str | None:
    """A service-account key names its account: label the connection with
    it, so the workspace sees which account to share resources with."""
    if auth_mode != AuthMode.SERVICE_ACCOUNT:
        return None
    email = secret.get("client_email")
    return email.strip()[:320] or None if isinstance(email, str) else None


def _validated_config(
    provider: Provider, raw: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """Validate ``raw`` with the provider's model; return its JSON form."""
    model = provider.config_model
    if model is None:
        if raw:
            raise InvalidRequestError(f"provider {provider.id!r} takes no config")
        return {}
    try:
        parsed = model.model_validate(dict(raw))
    except ValidationError as exc:
        raise InvalidRequestError(
            f"invalid config: {describe_validation_error(exc)}"
        ) from None
    dumped: dict[str, JsonValue] = parsed.model_dump(mode="json")
    return dumped


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
                config_schema=(
                    provider.config_model.model_json_schema()
                    if provider.config_model is not None
                    else None
                ),
                oauth=(
                    CatalogOAuth(
                        scopes=list(provider.oauth.scopes),
                        optional_scopes=list(provider.oauth.optional_scopes),
                        redirect_uri=(
                            services.oauth.redirect_uri(provider.id)
                            if services.oauth.configured
                            else None
                        ),
                    )
                    if provider.oauth is not None
                    else None
                ),
                capabilities=provider_capabilities(provider),
                sync_item_label=(
                    provider.sync_item_label
                    if isinstance(provider, SyncableProvider)
                    else None
                ),
            )
        )
    return CatalogResponse(providers=providers)


@router.get("/connections")
async def list_connections(
    caller: InternalCallerDep,
    services: ServicesDep,
    repo: ConnectionRepoDep,
    include_revoked: bool = False,
) -> ConnectionList:
    rows = await repo.list_connections(caller.org_id, include_revoked=include_revoked)
    return ConnectionList(connections=await _outs(services, caller.org_id, rows))


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
    if body.auth_mode == AuthMode.NONE:
        if body.secret:
            raise InvalidRequestError("a none-auth connection takes no secret")
    elif not body.secret:
        raise InvalidRequestError("secret: Field required")
    provider.validate_secret(body.auth_mode, body.secret)
    config = _validated_config(provider, body.config)
    info = await repo.create_connection(
        org_id=caller.org_id,
        provider=provider.id,
        auth_mode=body.auth_mode,
        secret=body.secret,
        account_label=body.account_label
        or _default_account_label(body.auth_mode, body.secret),
        scopes_granted=tuple(body.scopes_granted),
        config=config,
        created_by=caller.user_id,
    )
    return _out(info)


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: uuid.UUID,
    caller: InternalCallerDep,
    services: ServicesDep,
    repo: ConnectionRepoDep,
) -> ConnectionOut:
    info = await repo.get_connection(caller.org_id, connection_id)
    return await _one(services, caller.org_id, info)


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: uuid.UUID,
    body: UpdateConnectionRequest,
    caller: InternalCallerDep,
    services: ServicesDep,
    repo: ConnectionRepoDep,
) -> ConnectionOut:
    current = await repo.get_connection(caller.org_id, connection_id)
    provider = services.registry.get(current.provider)
    # Merge semantics: keys in the body replace stored keys, others are kept.
    config = _validated_config(provider, {**current.config, **body.config})
    info = await repo.update_config(caller.org_id, connection_id, config)
    return await _one(services, caller.org_id, info)


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: uuid.UUID,
    caller: InternalCallerDep,
    services: ServicesDep,
    repo: ConnectionRepoDep,
) -> ConnectionTestOut:
    current = await repo.get_connection(caller.org_id, connection_id)
    provider = services.registry.get(current.provider)
    ctx = await services.contexts.load(caller.org_id, connection_id, provider.id)
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
        ok=result.ok,
        message=result.message,
        connection=await _one(services, caller.org_id, info),
    )


@router.post("/connections/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def start_sync(
    connection_id: uuid.UUID, caller: InternalCallerDep, services: ServicesDep
) -> SyncStatusOut:
    """Start importing the connection's data in the background (providers
    with the ``sync`` capability). 409 while a sync of it is running."""
    started = await services.sync.start(caller.org_id, caller.user_id, connection_id)
    return SyncStatusOut.model_validate(started)


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
        exclusive=body.exclusive if body else False,
    )
    return IssuedKeyOut(
        id=issued.id, connection_id=issued.connection_id, key=issued.key
    )


@router.delete(
    "/connections/{connection_id}/keys", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_all_keys(
    connection_id: uuid.UUID, caller: InternalCallerDep, keys: KeyRepoDep
) -> Response:
    """Revoke every live key of the connection (e.g. keys orphaned by an
    activation whose rollback failed)."""
    await keys.revoke_all_keys(caller.org_id, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/connections/{connection_id}/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_key(
    connection_id: uuid.UUID,
    key_id: uuid.UUID,
    caller: InternalCallerDep,
    keys: KeyRepoDep,
) -> Response:
    await keys.revoke_key(caller.org_id, connection_id, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connection(
    connection_id: uuid.UUID, caller: InternalCallerDep, repo: ConnectionRepoDep
) -> Response:
    await repo.revoke_connection(caller.org_id, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

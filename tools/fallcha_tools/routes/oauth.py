"""OAuth2 with bring-your-own clients.

* ``/internal/provider-apps`` and ``/internal/oauth/start`` are called by the
  Fallcha API for a workspace user (internal secret + org/user headers).
* ``/oauth/{provider}/callback`` is public: the provider redirects the user's
  browser here. It always answers with a redirect to the fixed
  ``TOOLS_UI_RETURN_URL``, carrying only a result and a fixed reason code.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger

from fallcha_tools.core.auth import InternalCallerDep, require_internal_caller
from fallcha_tools.core.container import (
    ConnectionRepoDep,
    ProviderAppRepoDep,
    ServicesDep,
)
from fallcha_tools.core.oauth import (
    CallbackFailure,
    OAuthCallbackError,
    oauth_spec,
)
from fallcha_tools.core.provider import PROVIDER_ID_PATTERN, credential_family
from fallcha_tools.core.repositories import ProviderAppInfo
from fallcha_tools.schemas import (
    ConfirmConnectionRequest,
    ConnectionOut,
    CreateProviderAppRequest,
    OAuthStartOut,
    OAuthStartRequest,
    ProviderAppList,
    ProviderAppOut,
)

internal_router = APIRouter(
    prefix="/internal", dependencies=[Depends(require_internal_caller)]
)
public_router = APIRouter(prefix="/oauth")

# The callback URL carries the authorization code: never cache it, and never
# leak it to the next page through the Referer header.
_NO_LEAK_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _app_out(info: ProviderAppInfo) -> ProviderAppOut:
    return ProviderAppOut.model_validate(info)


@internal_router.get("/provider-apps")
async def list_provider_apps(
    caller: InternalCallerDep, apps: ProviderAppRepoDep
) -> ProviderAppList:
    rows = await apps.list_apps(caller.org_id)
    return ProviderAppList(provider_apps=[_app_out(row) for row in rows])


@internal_router.post("/provider-apps", status_code=status.HTTP_201_CREATED)
async def create_provider_app(
    body: CreateProviderAppRequest,
    caller: InternalCallerDep,
    services: ServicesDep,
    apps: ProviderAppRepoDep,
) -> ProviderAppOut:
    provider = services.registry.get(body.provider)
    oauth_spec(provider)  # 422 unless the provider supports OAuth2
    info = await apps.create(
        org_id=caller.org_id,
        # Stored under the family: one client serves all its providers.
        provider=credential_family(provider),
        client_id=body.client_id,
        client_secret=body.client_secret.get_secret_value(),
        created_by=caller.user_id,
    )
    return _app_out(info)


@internal_router.delete(
    "/provider-apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_provider_app(
    app_id: uuid.UUID, caller: InternalCallerDep, apps: ProviderAppRepoDep
) -> Response:
    await apps.delete_app(caller.org_id, app_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@internal_router.post("/oauth/start")
async def start_oauth(
    body: OAuthStartRequest, caller: InternalCallerDep, services: ServicesDep
) -> OAuthStartOut:
    started = await services.oauth.start(
        org_id=caller.org_id,
        user_id=caller.user_id,
        provider_id=body.provider,
        provider_app_id=body.provider_app_id,
        optional_scopes=body.optional_scopes,
        login_hint=body.login_hint,
    )
    return OAuthStartOut(
        authorization_url=started.authorization_url,
        redirect_uri=started.redirect_uri,
        expires_at=started.expires_at,
        browser_nonce=started.browser_nonce,
    )


@internal_router.post("/connections/{connection_id}/confirm")
async def confirm_connection(
    connection_id: uuid.UUID,
    body: ConfirmConnectionRequest,
    caller: InternalCallerDep,
    repo: ConnectionRepoDep,
) -> ConnectionOut:
    """Make a PENDING OAuth connection usable: only for the user who started
    the flow (``X-User-Id``), with the nonce from their browser."""
    info = await repo.confirm_pending(
        caller.org_id,
        connection_id,
        user_id=caller.user_id,
        nonce=body.browser_nonce.get_secret_value(),
    )
    return ConnectionOut.model_validate(info)


@public_router.get("/{provider_id}/callback", include_in_schema=False)
async def oauth_callback(
    provider_id: str,
    services: ServicesDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> Response:
    flow = services.oauth
    # Only a well-formed id is ever logged (the path is attacker-controlled).
    logged_id = provider_id if PROVIDER_ID_PATTERN.fullmatch(provider_id) else "?"
    target: str | None
    try:
        done = await flow.complete(provider_id, state=state, code=code, error=error)
        target = flow.success_url(done)
    except OAuthCallbackError as exc:
        logger.info("oauth callback for {} failed: {}", logged_id, exc.reason)
        target = flow.failure_url(exc.reason)
    except Exception as exc:  # never a 500 page with details
        logger.error("oauth callback for {} raised {}", logged_id, type(exc).__name__)
        target = flow.failure_url(CallbackFailure.INTERNAL_ERROR)
    if target is None:
        return JSONResponse(
            {"detail": "OAuth is not configured on this deployment"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers=_NO_LEAK_HEADERS,
        )
    return RedirectResponse(
        target, status_code=status.HTTP_302_FOUND, headers=_NO_LEAK_HEADERS
    )

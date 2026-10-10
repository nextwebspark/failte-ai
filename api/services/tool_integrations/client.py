"""HTTP client for the Fallcha tools service's ``/internal/*`` API.

Every request carries the shared ``X-Internal-Secret`` plus the acting
``X-Org-Id`` / ``X-User-Id``; the tools service scopes every connection by
that org. Request bodies and connection keys are never logged.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel, JsonValue, SecretStr, ValidationError

from api.errors.integrations import (
    IntegrationConflictError,
    IntegrationInvalidRequestError,
    IntegrationNotFoundError,
    IntegrationUnavailableError,
    ToolsServiceUnavailableError,
)
from api.schemas.integrations import (
    CreateProviderAppRequest,
    IntegrationCatalogResponse,
    IntegrationConnection,
    IntegrationSyncStatus,
    ProviderAppListResponse,
    ProviderAppResponse,
    StartOAuthRequest,
)

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
# Connection tests call the provider (e.g. Google), so allow a little longer.
TEST_TIMEOUT = httpx.Timeout(20.0, connect=3.0)
_MAX_DETAIL_CHARS = 300

_Model = TypeVar("_Model", bound=BaseModel)


_shared_http: httpx.AsyncClient | None = None


def shared_http_client() -> httpx.AsyncClient:
    """One pooled client per worker, created on first use."""
    global _shared_http
    if _shared_http is None or _shared_http.is_closed:
        _shared_http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    return _shared_http


async def close_shared_http_client() -> None:
    """Called on app shutdown."""
    global _shared_http
    if _shared_http is not None:
        await _shared_http.aclose()
        _shared_http = None


@dataclass(frozen=True, slots=True)
class Caller:
    """Who the tools service acts for."""

    org_id: int
    user_id: int


class _ConnectionList(BaseModel):
    connections: list[IntegrationConnection]


class IssuedConnectionKey(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    key: SecretStr


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    connection: IntegrationConnection


class StartedOAuth(BaseModel):
    """``oauth/start`` as the tools service answers it. The browser nonce goes
    to the starting user's browser only, never into a log."""

    authorization_url: str
    redirect_uri: str
    expires_at: datetime
    browser_nonce: SecretStr


class NewConnection(BaseModel):
    """Body of ``POST /internal/connections``."""

    provider: str
    auth_mode: str
    secret: dict[str, JsonValue]
    account_label: str | None = None
    scopes_granted: list[str]
    config: dict[str, JsonValue]
    reuse_secret_from: uuid.UUID | None = None


def _detail(response: httpx.Response, fallback: str) -> str:
    """The tools service's error detail. Its details never echo input."""
    try:
        body = response.json()
    except ValueError:
        return fallback
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str) and detail:
        text = detail
    elif isinstance(detail, list) and detail:
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc") or [])
                parts.append(
                    f"{loc}: {item.get('msg')}" if loc else str(item.get("msg"))
                )
        text = "; ".join(parts) or fallback
    else:
        text = fallback
    return text[:_MAX_DETAIL_CHARS]


class ToolsServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        internal_secret: str,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = internal_secret
        self._timeout = timeout
        self._http = http

    # -- catalog ---------------------------------------------------------

    async def get_catalog(self, caller: Caller) -> IntegrationCatalogResponse:
        response = await self._request("GET", "/internal/catalog", caller)
        return self._parse(response, IntegrationCatalogResponse)

    # -- connections -----------------------------------------------------

    async def list_connections(self, caller: Caller) -> list[IntegrationConnection]:
        response = await self._request("GET", "/internal/connections", caller)
        return self._parse(response, _ConnectionList).connections

    async def get_connection(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> IntegrationConnection:
        response = await self._request(
            "GET", f"/internal/connections/{connection_id}", caller
        )
        return self._parse(response, IntegrationConnection)

    async def create_connection(
        self, caller: Caller, body: NewConnection
    ) -> IntegrationConnection:
        response = await self._request(
            "POST",
            "/internal/connections",
            caller,
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return self._parse(response, IntegrationConnection)

    async def start_sync(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> IntegrationSyncStatus:
        """Start a background sync (409 while one runs)."""
        response = await self._request(
            "POST", f"/internal/connections/{connection_id}/sync", caller
        )
        return self._parse(response, IntegrationSyncStatus)

    async def update_config(
        self,
        caller: Caller,
        connection_id: uuid.UUID,
        config: Mapping[str, JsonValue],
    ) -> IntegrationConnection:
        response = await self._request(
            "PATCH",
            f"/internal/connections/{connection_id}",
            caller,
            json={"config": dict(config)},
        )
        return self._parse(response, IntegrationConnection)

    async def test_connection(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> ConnectionTestResult:
        response = await self._request(
            "POST",
            f"/internal/connections/{connection_id}/test",
            caller,
            timeout=TEST_TIMEOUT,
        )
        return self._parse(response, ConnectionTestResult)

    async def issue_key(
        self,
        caller: Caller,
        connection_id: uuid.UUID,
        *,
        fallcha_credential_uuid: str | None,
        exclusive: bool = False,
    ) -> IssuedConnectionKey:
        """With ``exclusive``, 409 if the connection already has a live key."""
        response = await self._request(
            "POST",
            f"/internal/connections/{connection_id}/keys",
            caller,
            json={
                "fallcha_credential_uuid": fallcha_credential_uuid,
                "exclusive": exclusive,
            },
        )
        return self._parse(response, IssuedConnectionKey)

    async def revoke_all_keys(self, caller: Caller, connection_id: uuid.UUID) -> None:
        await self._request(
            "DELETE", f"/internal/connections/{connection_id}/keys", caller
        )

    async def confirm_connection(
        self, caller: Caller, connection_id: uuid.UUID, *, browser_nonce: str
    ) -> IntegrationConnection:
        """PENDING -> ACTIVE for the user who started the OAuth flow (409
        otherwise); other connections are returned unchanged."""
        response = await self._request(
            "POST",
            f"/internal/connections/{connection_id}/confirm",
            caller,
            json={"browser_nonce": browser_nonce},
        )
        return self._parse(response, IntegrationConnection)

    async def revoke_key(
        self, caller: Caller, connection_id: uuid.UUID, key_id: uuid.UUID
    ) -> None:
        await self._request(
            "DELETE", f"/internal/connections/{connection_id}/keys/{key_id}", caller
        )

    # -- OAuth2 ----------------------------------------------------------

    async def list_provider_apps(self, caller: Caller) -> ProviderAppListResponse:
        response = await self._request("GET", "/internal/provider-apps", caller)
        return self._parse(response, ProviderAppListResponse)

    async def create_provider_app(
        self, caller: Caller, body: CreateProviderAppRequest
    ) -> ProviderAppResponse:
        response = await self._request(
            "POST",
            "/internal/provider-apps",
            caller,
            json={
                "provider": body.provider,
                "client_id": body.client_id,
                "client_secret": body.client_secret.get_secret_value(),
            },
        )
        return self._parse(response, ProviderAppResponse)

    async def delete_provider_app(self, caller: Caller, app_id: uuid.UUID) -> None:
        await self._request("DELETE", f"/internal/provider-apps/{app_id}", caller)

    async def start_oauth(
        self, caller: Caller, body: StartOAuthRequest
    ) -> StartedOAuth:
        response = await self._request(
            "POST",
            "/internal/oauth/start",
            caller,
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return self._parse(response, StartedOAuth)

    async def revoke_connection(self, caller: Caller, connection_id: uuid.UUID) -> None:
        """Revoke the connection and every key issued for it (idempotent)."""
        await self._request("DELETE", f"/internal/connections/{connection_id}", caller)

    # -- plumbing --------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        caller: Caller,
        *,
        json: dict[str, JsonValue] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        headers = {
            "X-Internal-Secret": self._secret,
            "X-Org-Id": str(caller.org_id),
            "X-User-Id": str(caller.user_id),
        }
        try:
            http = self._http or shared_http_client()
            response = await http.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                headers=headers,
                timeout=timeout or self._timeout,
            )
        except httpx.TimeoutException:
            logger.warning(f"Tools service {method} {path} timed out")
            raise ToolsServiceUnavailableError(
                "The tools service did not respond in time"
            ) from None
        except httpx.HTTPError as exc:
            logger.warning(
                f"Tools service {method} {path} failed: {type(exc).__name__}"
            )
            raise ToolsServiceUnavailableError() from None

        status = response.status_code
        if status < 400:
            return response
        logger.info(f"Tools service {method} {path} -> {status}")
        if status in (401, 403):
            logger.error(
                "Tools service rejected the internal secret; check "
                "TOOLS_INTERNAL_SECRET matches on both services"
            )
            raise ToolsServiceUnavailableError()
        if status == 404:
            raise IntegrationNotFoundError(_detail(response, "Not found"))
        if status == 409:
            raise IntegrationConflictError(_detail(response, "Conflict"))
        if status in (400, 422):
            raise IntegrationInvalidRequestError(_detail(response, "Invalid request"))
        if status == 503:
            # The tools service's detail names its env vars: keep it internal.
            logger.warning(f"Tools service {method} {path} -> 503 (not configured)")
            raise IntegrationUnavailableError(
                "This integration feature is not available on this deployment"
            )
        raise ToolsServiceUnavailableError()

    @staticmethod
    def _parse(response: httpx.Response, model: type[_Model]) -> _Model:
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError):
            logger.warning(
                f"Tools service returned an unexpected {model.__name__} payload"
            )
            raise ToolsServiceUnavailableError(
                "The tools service returned an unexpected response"
            ) from None

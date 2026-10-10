"""OAuth2 with bring-your-own clients: authorization code + PKCE, and lazy,
single-flight token refresh.

* :class:`OAuthFlow` starts an authorization (a random, single-use, 10-minute
  state bound to org, user, provider and client, with an encrypted PKCE
  verifier) and completes it from the provider's callback, creating an
  ``oauth2`` connection.
* :class:`OAuthTokenManager` hands out access tokens, refreshing one when it
  expires within :data:`REFRESH_MARGIN`. A refresh runs under a Postgres
  advisory lock on the connection plus a row lock, and re-reads the row once
  it holds them, so concurrent callers on any replica cause one refresh.

Nothing here logs a token, code, verifier, state or client secret.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import secrets
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from loguru import logger
from pydantic import JsonValue, ValidationError

from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.errors import (
    InvalidRequestError,
    ServiceUnavailableError,
    ToolsError,
)
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    AccessToken,
    OAuthSpec,
    Provider,
    ProviderRegistry,
)
from fallcha_tools.core.repositories import (
    REFRESH_TOKEN_KEY,
    ConnectionRepository,
    OAuthClient,
    OAuthStateRepository,
    OAuthTokenRepository,
    ProviderAppNotFoundError,
    ProviderAppRepository,
)

STATE_TTL = timedelta(minutes=10)
REFRESH_MARGIN = timedelta(minutes=5)
DEFAULT_EXPIRES_IN = 3600
# Token calls during a live tool call must be quick; the flow can wait longer.
REFRESH_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
EXCHANGE_TIMEOUT = httpx.Timeout(10.0, connect=3.0)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


# -- PKCE (RFC 7636) and state ------------------------------------------------


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    """86 characters from the unreserved set (RFC 7636 allows 43-128)."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """The S256 challenge: base64url(sha256(verifier)), unpadded."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# -- errors -------------------------------------------------------------------


class OAuthReconnectRequired(ToolsError):
    """The grant is unusable (revoked, expired, client removed): a workspace
    admin must reconnect. The message is safe to show to anyone."""


class OAuthRefreshFailed(ToolsError):
    """A transient refresh failure (network, timeout, provider outage)."""


class OAuthGrantError(Exception):
    """The token endpoint refused a grant. ``code`` is the OAuth error code."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(f"token endpoint returned {status_code} {code}")
        self.code = code
        self.status_code = status_code

    @property
    def grant_revoked(self) -> bool:
        return self.code == "invalid_grant"

    @property
    def client_rejected(self) -> bool:
        return self.code in {"invalid_client", "unauthorized_client"}


class OAuthTransportError(Exception):
    """The token endpoint could not be reached or answered unreadably."""


class CallbackFailure(StrEnum):
    """``reason`` codes the callback reports to the UI. Fixed strings only:
    nothing from the provider or the request is reflected."""

    INVALID_STATE = "invalid_state"
    EXPIRED_STATE = "expired_state"
    ACCESS_DENIED = "access_denied"
    AUTHORIZATION_FAILED = "authorization_failed"
    CLIENT_MISSING = "client_missing"
    TOKEN_EXCHANGE_FAILED = "token_exchange_failed"
    NO_REFRESH_TOKEN = "no_refresh_token"
    SCOPES_MISSING = "scopes_missing"
    INTERNAL_ERROR = "internal_error"


class OAuthCallbackError(Exception):
    def __init__(self, reason: CallbackFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


# -- token endpoint -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenGrant:
    access_token: str = field(repr=False)
    expires_at: datetime
    refresh_token: str | None = field(repr=False)
    # None when the response omitted ``scope`` (RFC 6749: same as requested).
    scopes: tuple[str, ...] | None


async def _token_request(
    http: httpx.AsyncClient,
    spec: OAuthSpec,
    form: Mapping[str, str],
    *,
    http_timeout: httpx.Timeout,
    now: datetime,
) -> TokenGrant:
    try:
        response = await http.post(
            spec.token_url,
            data=dict(form),
            headers={"Accept": "application/json"},
            timeout=http_timeout,
        )
    except httpx.HTTPError as exc:
        raise OAuthTransportError(type(exc).__name__) from None
    if response.status_code != 200:
        code = ""
        with contextlib.suppress(ValueError):
            body = response.json()
            if isinstance(body, dict):
                code = str(body.get("error", ""))[:64]
        # Status and error code only: the body may echo request parameters.
        logger.warning(
            "{} token grant failed: {} {}",
            spec.display_name,
            response.status_code,
            code,
        )
        if response.status_code >= 500 or response.status_code == 429:
            raise OAuthTransportError(f"HTTP {response.status_code}")
        raise OAuthGrantError(code, response.status_code)
    try:
        body = response.json()
        access_token = body["access_token"]
        if not isinstance(access_token, str) or not access_token:
            raise TypeError
        expires_in = int(body.get("expires_in") or DEFAULT_EXPIRES_IN)
        refresh_token = body.get("refresh_token")
        raw_scope = body.get("scope")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise OAuthTransportError("unreadable token response") from None
    return TokenGrant(
        access_token=access_token,
        expires_at=now + timedelta(seconds=max(expires_in, 0)),
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        scopes=tuple(raw_scope.split()) if isinstance(raw_scope, str) else None,
    )


async def exchange_code(
    http: httpx.AsyncClient,
    spec: OAuthSpec,
    client: OAuthClient,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    now: datetime,
    http_timeout: httpx.Timeout = EXCHANGE_TIMEOUT,
) -> TokenGrant:
    return await _token_request(
        http,
        spec,
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
        },
        http_timeout=http_timeout,
        now=now,
    )


async def refresh_grant(
    http: httpx.AsyncClient,
    spec: OAuthSpec,
    client: OAuthClient,
    *,
    refresh_token: str,
    now: datetime,
    http_timeout: httpx.Timeout = REFRESH_TIMEOUT,
) -> TokenGrant:
    return await _token_request(
        http,
        spec,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
        },
        http_timeout=http_timeout,
        now=now,
    )


async def fetch_account_email(
    http: httpx.AsyncClient,
    spec: OAuthSpec,
    access_token: str,
    *,
    http_timeout: httpx.Timeout = EXCHANGE_TIMEOUT,
) -> str | None:
    """The account's email from the userinfo endpoint, or None (best effort:
    it only labels the connection)."""
    if not spec.userinfo_url:
        return None
    try:
        response = await http.get(
            spec.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=http_timeout,
        )
        if response.status_code != 200:
            logger.info(
                "{} userinfo returned {}", spec.display_name, response.status_code
            )
            return None
        email = response.json().get("email")
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    if isinstance(email, str) and 3 <= len(email) <= 320 and "@" in email:
        return email
    return None


# -- authorization flow -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StartedAuthorization:
    authorization_url: str
    redirect_uri: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CompletedAuthorization:
    connection_id: uuid.UUID
    provider: str


def oauth_spec(provider: Provider) -> OAuthSpec:
    spec = provider.oauth
    if spec is None or AuthMode.OAUTH2 not in provider.auth_modes:
        raise InvalidRequestError(f"provider {provider.id!r} does not support oauth2")
    return spec


def _with_query(base: str, params: Mapping[str, str]) -> str:
    parts = urlsplit(base)
    query = [*parse_qsl(parts.query, keep_blank_values=True), *params.items()]
    return urlunsplit(parts._replace(query=urlencode(query)))


@dataclass(frozen=True, slots=True)
class OAuthFlow:
    db: Database
    box: SecretBox
    http: httpx.AsyncClient
    registry: ProviderRegistry
    public_base_url: str
    ui_return_url: str
    clock: Clock = utc_now

    def _require_configured(self) -> None:
        if not self.public_base_url or not self.ui_return_url:
            raise ServiceUnavailableError(
                "OAuth is not configured on this deployment: set "
                "TOOLS_PUBLIC_BASE_URL and TOOLS_UI_RETURN_URL on the tools service"
            )

    def redirect_uri(self, provider_id: str) -> str:
        return f"{self.public_base_url}/oauth/{provider_id}/callback"

    async def start(
        self,
        *,
        org_id: int,
        user_id: int,
        provider_id: str,
        provider_app_id: uuid.UUID,
        optional_scopes: Sequence[str] = (),
    ) -> StartedAuthorization:
        self._require_configured()
        provider = self.registry.get(provider_id)
        spec = oauth_spec(provider)
        unknown = sorted(set(optional_scopes) - set(spec.optional_scopes))
        if unknown:
            raise InvalidRequestError(
                f"not optional scopes of {provider.id!r}: {', '.join(unknown)}"
            )
        async with self.db.session() as session:
            app = await ProviderAppRepository(session, self.box).get(
                org_id, provider_app_id
            )
            if app.provider != provider.id:
                raise ProviderAppNotFoundError("OAuth client not found")
            state, verifier = new_state(), new_code_verifier()
            now = self.clock()
            expires_at = now + STATE_TTL
            redirect_uri = self.redirect_uri(provider.id)
            await OAuthStateRepository(session, self.box).create(
                state=state,
                org_id=org_id,
                user_id=user_id,
                provider=provider.id,
                provider_app_id=app.id,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
                expires_at=expires_at,
                now=now,
            )
        scopes = dict.fromkeys(
            [*spec.identity_scopes, *spec.scopes, *optional_scopes]
        )  # ordered, de-duplicated
        params = {
            **spec.authorize_params,
            "response_type": "code",
            "client_id": app.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        return StartedAuthorization(
            authorization_url=_with_query(spec.authorize_url, params),
            redirect_uri=redirect_uri,
            expires_at=expires_at,
        )

    async def complete(
        self,
        provider_id: str,
        *,
        state: str | None,
        code: str | None,
        error: str | None,
    ) -> CompletedAuthorization:
        """Raises :class:`OAuthCallbackError` with a fixed reason code."""
        self._require_configured()
        if not state or len(state) > 256:
            raise OAuthCallbackError(CallbackFailure.INVALID_STATE)
        async with self.db.session() as session:
            pending = await OAuthStateRepository(session, self.box).consume(state)
        if pending is None or pending.provider != provider_id:
            raise OAuthCallbackError(CallbackFailure.INVALID_STATE)
        now = self.clock()
        if pending.expires_at <= now:
            raise OAuthCallbackError(CallbackFailure.EXPIRED_STATE)
        if error:
            raise OAuthCallbackError(
                CallbackFailure.ACCESS_DENIED
                if error == "access_denied"
                else CallbackFailure.AUTHORIZATION_FAILED
            )
        if not code or len(code) > 2048:
            raise OAuthCallbackError(CallbackFailure.AUTHORIZATION_FAILED)
        provider = self.registry.get(provider_id)
        spec = oauth_spec(provider)
        if pending.provider_app_id is None or pending.redirect_uri is None:
            raise OAuthCallbackError(CallbackFailure.CLIENT_MISSING)
        async with self.db.session() as session:
            try:
                client = await ProviderAppRepository(session, self.box).client(
                    pending.org_id, pending.provider_app_id
                )
            except ProviderAppNotFoundError:
                raise OAuthCallbackError(CallbackFailure.CLIENT_MISSING) from None
        try:
            grant = await exchange_code(
                self.http,
                spec,
                client,
                code=code,
                code_verifier=pending.code_verifier,
                redirect_uri=pending.redirect_uri,
                now=now,
            )
        except (OAuthGrantError, OAuthTransportError):
            raise OAuthCallbackError(CallbackFailure.TOKEN_EXCHANGE_FAILED) from None
        if not grant.refresh_token:
            raise OAuthCallbackError(CallbackFailure.NO_REFRESH_TOKEN)
        requested = (*spec.identity_scopes, *spec.scopes)
        granted = grant.scopes if grant.scopes is not None else requested
        if not set(spec.scopes) <= set(granted):
            # The user unticked a required permission on the consent screen.
            raise OAuthCallbackError(CallbackFailure.SCOPES_MISSING)
        label = await fetch_account_email(self.http, spec, grant.access_token)
        config = _default_config(provider, spec)
        async with self.db.session() as session:
            info = await ConnectionRepository(session, self.box).create_connection(
                org_id=pending.org_id,
                provider=provider.id,
                auth_mode=AuthMode.OAUTH2,
                secret={REFRESH_TOKEN_KEY: grant.refresh_token},
                account_label=label,
                scopes_granted=tuple(granted),
                config=config,
                created_by=pending.user_id,
                provider_app_id=pending.provider_app_id,
                access_token=grant.access_token,
                expires_at=grant.expires_at,
            )
        logger.info(
            "oauth connection {} created for org {} ({})",
            info.id,
            pending.org_id,
            provider.id,
        )
        return CompletedAuthorization(connection_id=info.id, provider=provider.id)

    def success_url(self, done: CompletedAuthorization) -> str:
        return _with_query(
            self.ui_return_url,
            {
                "integration_result": "success",
                "connection_id": str(done.connection_id),
                "provider": done.provider,
            },
        )

    def failure_url(self, reason: CallbackFailure) -> str | None:
        """None when no return URL is configured."""
        if not self.ui_return_url:
            return None
        return _with_query(
            self.ui_return_url,
            {"integration_result": "error", "reason": reason.value},
        )


def _default_config(provider: Provider, spec: OAuthSpec) -> dict[str, JsonValue]:
    model = provider.config_model
    if model is None or not spec.default_config:
        return {}
    try:
        dumped: dict[str, JsonValue] = model.model_validate(
            dict(spec.default_config)
        ).model_dump(mode="json")
    except ValidationError:
        logger.error("default OAuth config of {} is invalid", provider.id)
        return {}
    return dumped


# -- token refresh ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OAuthTokenManager:
    """Fresh access tokens for OAuth2 connections (see the module docstring)."""

    db: Database
    box: SecretBox
    http: httpx.AsyncClient
    clock: Clock = utc_now
    timeout: httpx.Timeout = field(default_factory=lambda: REFRESH_TIMEOUT)

    def is_fresh(self, expires_at: datetime | None) -> bool:
        return expires_at is not None and expires_at - REFRESH_MARGIN > self.clock()

    async def access_token(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        spec: OAuthSpec,
        *,
        rejected: str | None = None,
    ) -> AccessToken:
        reconnect = f"{spec.display_name} access was revoked or expired; reconnect"
        async with self.db.session() as session:
            repo = OAuthTokenRepository(session, self.box)
            await repo.lock(connection_id)
            current = await repo.load(org_id, connection_id)
            if (
                current.access_token
                and current.access_token != rejected
                and current.expires_at is not None
                and self.is_fresh(current.expires_at)
            ):
                # Another caller refreshed while we waited for the lock.
                await session.rollback()
                return AccessToken(current.access_token, current.expires_at)
            if current.refresh_token is None:
                await session.rollback()
                raise OAuthReconnectRequired(reconnect)
            if current.client is None:
                message = (
                    f"the {spec.display_name} OAuth client of this connection was "
                    "removed; reconnect"
                )
                await repo.mark_error(message, drop_tokens=False)
                raise OAuthReconnectRequired(message)
            try:
                grant = await refresh_grant(
                    self.http,
                    spec,
                    current.client,
                    refresh_token=current.refresh_token,
                    now=self.clock(),
                    http_timeout=self.timeout,
                )
            except OAuthGrantError as exc:
                if exc.client_rejected:
                    message = (
                        f"{spec.display_name} rejected the OAuth client (check its "
                        "client ID and secret); reconnect"
                    )
                    await repo.mark_error(message, drop_tokens=False)
                    raise OAuthReconnectRequired(message) from None
                # invalid_grant, and any other refusal of the refresh token.
                await repo.mark_error(reconnect, drop_tokens=exc.grant_revoked)
                logger.warning(
                    "oauth connection {} needs reconnecting ({})",
                    connection_id,
                    exc.code,
                )
                raise OAuthReconnectRequired(reconnect) from None
            except OAuthTransportError:
                await session.rollback()
                raise OAuthRefreshFailed(
                    f"could not reach {spec.display_name} to refresh access; "
                    "please try again"
                ) from None
            await repo.save(
                access_token=grant.access_token,
                expires_at=grant.expires_at,
                refresh_token=grant.refresh_token,
                scopes_granted=grant.scopes,
            )
            return AccessToken(grant.access_token, grant.expires_at)


@dataclass(frozen=True, slots=True)
class ConnectionTokens:
    """:class:`~fallcha_tools.core.provider.OAuthAccess` for one connection.

    Serves the token loaded with the connection while it is fresh; otherwise
    asks the manager (which refreshes under the locks).
    """

    manager: OAuthTokenManager
    org_id: int
    connection_id: uuid.UUID
    spec: OAuthSpec
    loaded: AccessToken | None = None

    async def access_token(self, *, rejected: str | None = None) -> AccessToken:
        loaded = self.loaded
        if (
            loaded is not None
            and loaded.token != rejected
            and self.manager.is_fresh(loaded.expires_at)
        ):
            return loaded
        return await self.manager.access_token(
            self.org_id, self.connection_id, self.spec, rejected=rejected
        )

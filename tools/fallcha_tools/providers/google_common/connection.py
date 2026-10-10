"""Turn a connection context into Google credentials, for any Google provider.

Holds the process-wide caches (tokens, parsed service-account keys) that a
provider shares across calls, and builds the right
:class:`GoogleCredentialsSource` for the connection's auth mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx
from pydantic import JsonValue, ValidationError

from fallcha_tools.core.errors import InvalidRequestError, describe_validation_error
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import ConnectionContext, OAuthSpec
from fallcha_tools.providers.google_common.credentials import (
    GOOGLE_TOKEN_URL,
    Clock,
    GoogleCredentialsSource,
    OAuthCredentials,
    ServiceAccountCredentials,
    SignerCache,
    TokenCache,
    utc_now,
)
from fallcha_tools.providers.google_common.errors import NotConfiguredError
from fallcha_tools.providers.google_common.http import DEFAULT_TIMEOUT
from fallcha_tools.providers.google_common.scopes import (
    GOOGLE_AUTHORIZE_PARAMS,
    GOOGLE_AUTHORIZE_URL,
    GOOGLE_IDENTITY_SCOPES,
    GOOGLE_USERINFO_URL,
)
from fallcha_tools.providers.google_common.service_account import ServiceAccountKey

GOOGLE_AUTH_MODES = frozenset({AuthMode.SERVICE_ACCOUNT, AuthMode.OAUTH2})


def google_oauth_spec(
    *,
    scopes: tuple[str, ...],
    optional_scopes: tuple[str, ...] = (),
    default_config: Mapping[str, JsonValue] | None = None,
) -> OAuthSpec:
    """Google's OAuth2 endpoints with offline access and the account email."""
    return OAuthSpec(
        display_name="Google",
        authorize_url=GOOGLE_AUTHORIZE_URL,
        token_url=GOOGLE_TOKEN_URL,
        userinfo_url=GOOGLE_USERINFO_URL,
        scopes=scopes,
        optional_scopes=optional_scopes,
        identity_scopes=GOOGLE_IDENTITY_SCOPES,
        authorize_params=dict(GOOGLE_AUTHORIZE_PARAMS),
        default_config=dict(default_config or {}),
    )


def validate_google_secret(
    auth_mode: AuthMode, secret: Mapping[str, JsonValue]
) -> None:
    """Service-account keys are parsed up front; OAuth secrets never reach
    here (the callback stores them)."""
    if auth_mode != AuthMode.SERVICE_ACCOUNT:
        return
    try:
        ServiceAccountKey.model_validate(dict(secret))
    except ValidationError as exc:
        raise InvalidRequestError(
            f"invalid service-account key: {describe_validation_error(exc)}"
        ) from None


@dataclass(frozen=True, slots=True)
class GoogleAuth:
    """The connection's credentials plus a hint of which account they are
    (the service account's email, or the OAuth account's label)."""

    credentials: GoogleCredentialsSource
    account_hint: str | None


@dataclass(frozen=True)
class GoogleAuthFactory:
    """Builds :class:`GoogleAuth` for a connection; owns the shared caches."""

    product: str
    token_cache: TokenCache = field(default_factory=TokenCache)
    signer_cache: SignerCache = field(default_factory=SignerCache)
    clock: Clock = utc_now
    request_timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)

    def for_context(self, ctx: ConnectionContext) -> GoogleAuth:
        if ctx.auth_mode == AuthMode.OAUTH2:
            if ctx.oauth is None:
                raise NotConfiguredError("this Google connection is not usable")
            return GoogleAuth(
                credentials=OAuthCredentials(
                    connection_id=ctx.connection_id,
                    tokens=ctx.oauth,
                    cache=self.token_cache,
                    scopes_granted=ctx.scopes_granted,
                ),
                account_hint=ctx.account_label,
            )
        if ctx.auth_mode != AuthMode.SERVICE_ACCOUNT:
            raise NotConfiguredError(
                f"{ctx.auth_mode} connections are not supported by {self.product}"
            )
        try:
            signer = self.signer_cache.get(ctx.connection_id, ctx.secret)
        except ValidationError:
            raise NotConfiguredError(
                "the service-account key for this connection is invalid"
            ) from None
        return GoogleAuth(
            credentials=ServiceAccountCredentials(
                connection_id=ctx.connection_id,
                signer=signer,
                http=ctx.http,
                cache=self.token_cache,
                timeout=self.request_timeout,
                clock=self.clock,
            ),
            account_hint=signer.client_email,
        )

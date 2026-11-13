"""Signing in with Microsoft (the Microsoft identity platform, OAuth2 v2.0).

The authorization-code flow, PKCE and refresh are the core's
(:mod:`fallcha_tools.core.oauth`); this module only describes Microsoft's
endpoints and scopes, and serves a connection's tokens to Graph calls.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from fallcha_tools.core.errors import ToolsError
from fallcha_tools.core.oauth import OAuthReconnectRequired, OAuthRefreshFailed
from fallcha_tools.core.provider import OAuthAccess, OAuthSpec
from fallcha_tools.providers.google_common.credentials import CachedToken, TokenCache
from fallcha_tools.providers.google_common.errors import (
    GoogleApiError,
    NotConfiguredError,
)

# Outlook connections use Microsoft's OAuth clients only.
MICROSOFT_FAMILY = "microsoft"
LOGIN_BASE = "https://login.microsoftonline.com"
GRAPH_API = "https://graph.microsoft.com/v1.0"
GRAPH_RESOURCE = "https://graph.microsoft.com/"

# Delegated Microsoft Graph permissions. Calendars.ReadWrite covers reading
# free/busy and events and creating, changing and deleting events; User.Read
# only reads the account's address to label the connection.
CALENDARS_SCOPE = "Calendars.ReadWrite"
USER_READ_SCOPE = "User.Read"
# A refresh token. Microsoft never lists it among the granted scopes.
OFFLINE_SCOPE = "offline_access"
MICROSOFT_SCOPES = (CALENDARS_SCOPE, USER_READ_SCOPE)


def authority(tenant: str) -> str:
    return f"{LOGIN_BASE}/{tenant}/oauth2/v2.0"


def microsoft_oauth_spec(
    tenant: str, *, default_config: Mapping[str, JsonValue] | None = None
) -> OAuthSpec:
    """Microsoft's v2.0 endpoints for ``tenant`` ("common": work, school and
    personal accounts). ``prompt=select_account`` lets an owner pick which
    of their Microsoft accounts to connect. Microsoft has no revocation
    endpoint for a refresh token: erasing a workspace forgets it instead."""
    base = authority(tenant)
    return OAuthSpec(
        display_name="Microsoft",
        authorize_url=f"{base}/authorize",
        token_url=f"{base}/token",
        userinfo_url=f"{GRAPH_API}/me",
        revocation_url=None,
        scopes=MICROSOFT_SCOPES,
        identity_scopes=(OFFLINE_SCOPE,),
        authorize_params={"prompt": "select_account", "response_mode": "query"},
        default_config=dict(default_config or {}),
        userinfo_email_fields=("mail", "userPrincipalName"),
        scope_prefixes=(GRAPH_RESOURCE,),
    )


class MicrosoftCredentials:
    """Access tokens of one Outlook connection, via the process cache (one
    refresh at a time in process; the token manager covers other replicas).
    One token covers every granted scope."""

    def __init__(
        self,
        *,
        connection_id: uuid.UUID,
        tokens: OAuthAccess,
        cache: TokenCache,
        scopes_granted: Sequence[str],
    ) -> None:
        self._key = (connection_id, "microsoft-oauth2", ())
        self._tokens = tokens
        self._cache = cache
        self._granted = frozenset(scopes_granted)
        self._last: str | None = None

    async def access_token(self, scopes: Sequence[str]) -> str:
        if not set(scopes) <= self._granted:
            raise NotConfiguredError(
                "the connected Microsoft account did not allow access to its "
                "calendar; reconnect and allow it"
            )
        token = await self._cache.get_or_mint(self._key, self._mint)
        self._last = token
        return token

    def invalidate(self, scopes: Sequence[str]) -> None:
        del scopes
        self._cache.invalidate(self._key, rejected=self._last)

    async def _mint(self) -> CachedToken:
        try:
            issued = await self._tokens.access_token(
                rejected=self._cache.rejected(self._key)
            )
        except OAuthReconnectRequired as exc:
            raise NotConfiguredError(str(exc)) from None
        except OAuthRefreshFailed as exc:
            raise GoogleApiError(str(exc)) from None
        except ToolsError:  # e.g. revoked or deleted meanwhile
            raise NotConfiguredError(
                "this Microsoft connection is no longer usable; reconnect"
            ) from None
        return CachedToken(token=issued.token, expires_at=issued.expires_at)

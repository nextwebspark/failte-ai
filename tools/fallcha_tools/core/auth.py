"""Two ways in:

* ``/internal/*`` is called only by the Fallcha API, with a shared
  ``X-Internal-Secret`` plus the acting ``X-Org-Id`` / ``X-User-Id``.
* ``/mcp/{provider}`` is called by the voice engine with
  ``Authorization: Bearer <connection key>``; the key pins org, connection
  and provider.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastmcp.server.auth import AccessToken, TokenVerifier
from loguru import logger

from fallcha_tools.core.container import ServicesDep
from fallcha_tools.core.repositories import KeyPrincipal


@dataclass(frozen=True, slots=True)
class InternalCaller:
    org_id: int
    user_id: int


def secrets_match(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


_ID_PATTERN = re.compile(r"^[0-9]{1,18}$")
_BIGINT_MAX = 2**63 - 1


def _positive_int(value: str | None) -> int | None:
    """A positive id that fits the BIGINT columns, else None."""
    if value is None or not _ID_PATTERN.fullmatch(value):
        return None
    parsed = int(value)
    return parsed if 0 < parsed <= _BIGINT_MAX else None


def require_internal_caller(
    services: ServicesDep,
    x_internal_secret: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
) -> InternalCaller:
    # The secret is checked before anything else is parsed, so an
    # unauthenticated caller learns nothing beyond "401".
    expected = services.settings.internal_secret.get_secret_value()
    if not secrets_match(x_internal_secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal secret")
    org_id, user_id = _positive_int(x_org_id), _positive_int(x_user_id)
    if org_id is None or user_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "X-Org-Id and X-User-Id headers must be positive integers",
        )
    return InternalCaller(org_id=org_id, user_id=user_id)


InternalCallerDep = Annotated[InternalCaller, Depends(require_internal_caller)]

KeyLookup = Callable[[str], Awaitable[KeyPrincipal | None]]

CLAIM_ORG_ID = "org_id"
CLAIM_CONNECTION_ID = "connection_id"
CLAIM_PROVIDER = "provider"


class ConnectionKeyVerifier(TokenVerifier):
    """Accepts a connection key only at its own provider's MCP endpoint."""

    def __init__(self, provider_id: str, lookup: KeyLookup) -> None:
        super().__init__()
        self._provider_id = provider_id
        self._lookup = lookup

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await self._lookup(token)
        if principal is None:
            return None
        if principal.provider != self._provider_id:
            logger.warning(
                "connection key {} for provider {} used at /mcp/{}",
                principal.key_id,
                principal.provider,
                self._provider_id,
            )
            return None
        return AccessToken(
            token=token,
            client_id=str(principal.connection_id),
            scopes=[],
            claims={
                CLAIM_ORG_ID: principal.org_id,
                CLAIM_CONNECTION_ID: str(principal.connection_id),
                CLAIM_PROVIDER: principal.provider,
            },
        )

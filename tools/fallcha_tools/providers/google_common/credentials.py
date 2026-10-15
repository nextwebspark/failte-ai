"""Where Google access tokens come from.

Every Google provider's calls only need ``await source.access_token(scopes)``;
which grant produced the token is the source's business:

* :class:`ServiceAccountCredentials` mints tokens with the JWT-bearer grant
  (RFC 7523).
* :class:`OAuthCredentials` serves an OAuth2 connection's token, refreshed by
  the core's :class:`~fallcha_tools.core.oauth.OAuthTokenManager`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from loguru import logger
from pydantic import JsonValue

from fallcha_tools.core.errors import ToolsError
from fallcha_tools.core.oauth import OAuthReconnectRequired, OAuthRefreshFailed
from fallcha_tools.core.provider import OAuthAccess
from fallcha_tools.providers.google_common.errors import (
    GoogleApiError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_common.service_account import ServiceAccountKey

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ASSERTION_LIFETIME = timedelta(hours=1)
# A cached token is replaced this long before Google says it expires.
REFRESH_MARGIN = timedelta(minutes=5)
MAX_CACHED_TOKENS = 4096
MAX_CACHED_SIGNERS = 1024

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class GoogleCredentialsSource(Protocol):
    """Supplies bearer tokens for Google APIs, for one connection."""

    async def access_token(self, scopes: Sequence[str]) -> str: ...

    def invalidate(self, scopes: Sequence[str]) -> None:
        """Forget the cached token for ``scopes`` (Google rejected it)."""
        ...


@dataclass(frozen=True, slots=True)
class CachedToken:
    token: str
    expires_at: datetime


CacheKey = tuple[uuid.UUID, str, tuple[str, ...]]


class TokenCache:
    """Process-wide token cache with single-flight minting per key.

    Keys include the connection and the scope set, so connections never share
    tokens and a narrower-scoped token is never reused for a wider call.
    Concurrent misses for one key await the same mint task; the in-flight
    map only holds keys that are being minted right now, so it stays small.
    """

    def __init__(
        self, clock: Clock = utc_now, max_entries: int = MAX_CACHED_TOKENS
    ) -> None:
        self._clock = clock
        self._max_entries = max_entries
        self._tokens: dict[CacheKey, CachedToken] = {}
        self._inflight: dict[CacheKey, asyncio.Task[CachedToken]] = {}
        # The last token the provider refused, per key, shared by every
        # caller in the process (see :meth:`invalidate`).
        self._rejected: OrderedDict[CacheKey, str] = OrderedDict()

    def _fresh(self, key: CacheKey) -> str | None:
        cached = self._tokens.get(key)
        if cached is not None and cached.expires_at - REFRESH_MARGIN > self._clock():
            return cached.token
        return None

    async def get_or_mint(
        self, key: CacheKey, mint: Callable[[], Awaitable[CachedToken]]
    ) -> str:
        token = self._fresh(key)
        if token is not None:
            return token
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._mint_and_store(key, mint))
            self._inflight[key] = task
            task.add_done_callback(lambda done: self._finished(key, done))
        # Shielded: one cancelled caller must not cancel the mint for others.
        return (await asyncio.shield(task)).token

    def invalidate(self, key: CacheKey, rejected: str | None = None) -> None:
        """Forget the cached token. With ``rejected`` (the token the provider
        refused), only that token is forgotten: if another caller already
        replaced it, the replacement stays. ``rejected`` is remembered so a
        later mint, by any caller, never hands it out again."""
        if rejected is None:
            self._tokens.pop(key, None)
            return
        self._rejected[key] = rejected
        self._rejected.move_to_end(key)
        while len(self._rejected) > self._max_entries:
            self._rejected.popitem(last=False)
        cached = self._tokens.get(key)
        if cached is not None and cached.token == rejected:
            del self._tokens[key]

    def rejected(self, key: CacheKey) -> str | None:
        return self._rejected.get(key)

    def __len__(self) -> int:
        return len(self._tokens)

    @property
    def minting(self) -> int:
        """Keys with a mint in flight (for tests and metrics)."""
        return len(self._inflight)

    async def _mint_and_store(
        self, key: CacheKey, mint: Callable[[], Awaitable[CachedToken]]
    ) -> CachedToken:
        minted = await mint()
        self._tokens[key] = minted
        self._prune()
        return minted

    def _finished(self, key: CacheKey, done: asyncio.Task[CachedToken]) -> None:
        if self._inflight.get(key) is done:
            del self._inflight[key]
        if not done.cancelled():
            done.exception()  # retrieved: no "never retrieved" warning

    def _prune(self) -> None:
        now = self._clock()
        for stale in [k for k, v in self._tokens.items() if v.expires_at <= now]:
            del self._tokens[stale]
        overflow = len(self._tokens) - self._max_entries
        if overflow > 0:
            soonest = sorted(self._tokens, key=lambda k: self._tokens[k].expires_at)
            for key in soonest[:overflow]:
                del self._tokens[key]


@dataclass(frozen=True, slots=True)
class ServiceAccountSigner:
    """A parsed service-account key, ready to sign assertions."""

    client_email: str
    key_id: str | None
    private_key: RSAPrivateKey

    def sign_assertion(self, scopes: Sequence[str], issued_at: datetime) -> str:
        """A signed RS256 JWT asserting ``client_email`` for ``scopes``."""
        header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
        if self.key_id:
            header["kid"] = self.key_id
        iat = int(issued_at.timestamp())
        claims = {
            "iss": self.client_email,
            "scope": " ".join(scopes),
            "aud": GOOGLE_TOKEN_URL,
            "iat": iat,
            "exp": iat + int(ASSERTION_LIFETIME.total_seconds()),
        }
        signing_input = ".".join(
            _b64url(json.dumps(part, separators=(",", ":")).encode())
            for part in (header, claims)
        )
        signature = self.private_key.sign(
            signing_input.encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{signing_input}.{_b64url(signature)}"


SignerKey = tuple[uuid.UUID, str | None, str | None]


class SignerCache:
    """Parsed keys per (connection, key id), so the hot path skips PEM/RSA work.

    A connection's secret never changes in place (reconnecting creates a new
    connection), so the connection id plus the key id identify the key.
    """

    def __init__(self, max_entries: int = MAX_CACHED_SIGNERS) -> None:
        self._max_entries = max_entries
        self._signers: OrderedDict[SignerKey, ServiceAccountSigner] = OrderedDict()

    def get(
        self, connection_id: uuid.UUID, secret: Mapping[str, JsonValue]
    ) -> ServiceAccountSigner:
        """Raises ``pydantic.ValidationError`` if the key is unusable."""
        key_id, email = secret.get("private_key_id"), secret.get("client_email")
        cache_key: SignerKey = (
            connection_id,
            key_id if isinstance(key_id, str) else None,
            email if isinstance(email, str) else None,
        )
        signer = self._signers.get(cache_key)
        if signer is not None:
            self._signers.move_to_end(cache_key)
            return signer
        parsed = ServiceAccountKey.model_validate(dict(secret))
        signer = ServiceAccountSigner(
            client_email=parsed.client_email,
            key_id=parsed.private_key_id,
            private_key=parsed.signer(),
        )
        self._signers[cache_key] = signer
        while len(self._signers) > self._max_entries:
            self._signers.popitem(last=False)
        return signer


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class ServiceAccountCredentials:
    """Mints tokens for one connection's service account, via the cache."""

    connection_id: uuid.UUID
    signer: ServiceAccountSigner
    http: httpx.AsyncClient
    cache: TokenCache
    timeout: httpx.Timeout
    clock: Clock = utc_now

    def _key(self, scopes: Sequence[str]) -> CacheKey:
        return (self.connection_id, self.signer.client_email, tuple(sorted(scopes)))

    async def access_token(self, scopes: Sequence[str]) -> str:
        key = self._key(scopes)
        return await self.cache.get_or_mint(key, lambda: self._mint(key[2]))

    def invalidate(self, scopes: Sequence[str]) -> None:
        self.cache.invalidate(self._key(scopes))

    async def _mint(self, scopes: tuple[str, ...]) -> CachedToken:
        now = self.clock()
        assertion = self.signer.sign_assertion(scopes, now)
        try:
            response = await self.http.post(
                GOOGLE_TOKEN_URL,
                data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion},
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise GoogleApiError("Google sign-in timed out; please try again") from None
        except httpx.HTTPError:
            raise GoogleApiError("could not reach Google to sign in") from None
        if response.status_code != 200:
            raise _token_error(response)
        try:
            body = response.json()
            token = str(body["access_token"])
            expires_in = int(body.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError):
            raise GoogleApiError(
                "Google returned an unreadable sign-in response"
            ) from None
        return CachedToken(token=token, expires_at=now + timedelta(seconds=expires_in))


class OAuthCredentials:
    """Tokens of one OAuth2 connection.

    One token covers every granted scope, so the cache key ignores scopes;
    instead each request's scopes are checked against what the user granted.
    The process cache adds in-process single-flight (and shields a refresh
    from a cancelled caller, so a rotated refresh token is always stored);
    the token manager adds cross-process single-flight.
    """

    def __init__(
        self,
        *,
        connection_id: uuid.UUID,
        tokens: OAuthAccess,
        cache: TokenCache,
        scopes_granted: Sequence[str],
    ) -> None:
        self._connection_id = connection_id
        self._tokens = tokens
        self._cache = cache
        self._granted = frozenset(scopes_granted)
        self._last: str | None = None

    @property
    def _key(self) -> CacheKey:
        return (self._connection_id, "oauth2", ())

    async def access_token(self, scopes: Sequence[str]) -> str:
        for scope in scopes:
            self._require(scope)
        token = await self._cache.get_or_mint(self._key, self._mint)
        self._last = token
        return token

    def invalidate(self, scopes: Sequence[str]) -> None:
        del scopes  # one token for all scopes
        # Google refused the token: no caller may be handed it again. The
        # rejection lives in the shared cache, since every tool call builds
        # its own credentials object (and context holding the old token).
        self._cache.invalidate(self._key, rejected=self._last)

    def _require(self, scope: str) -> None:
        options = _SATISFIED_BY.get(scope, (frozenset({scope}),))
        if not any(option <= self._granted for option in options):
            raise NotConfiguredError(
                f"the connected Google account did not allow access to "
                f"{_SCOPE_NAMES.get(scope, 'this Google service')}; reconnect "
                "and allow it"
            )

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
                "this Google connection is no longer usable; reconnect"
            ) from None
        return CachedToken(token=issued.token, expires_at=issued.expires_at)


_SATISFIED_BY: dict[str, tuple[frozenset[str], ...]] = {
    "https://www.googleapis.com/auth/calendar": (
        frozenset({"https://www.googleapis.com/auth/calendar"}),
        frozenset(
            {
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
            }
        ),
    ),
    "https://www.googleapis.com/auth/spreadsheets.readonly": (
        frozenset({"https://www.googleapis.com/auth/spreadsheets.readonly"}),
        frozenset({"https://www.googleapis.com/auth/spreadsheets"}),
    ),
}
_SCOPE_NAMES = {
    "https://www.googleapis.com/auth/calendar": "Google Calendar",
    "https://www.googleapis.com/auth/spreadsheets.readonly": (
        "Google Sheets (order lookup)"
    ),
    "https://www.googleapis.com/auth/spreadsheets": "Google Sheets",
}


def _token_error(response: httpx.Response) -> GoogleApiError:
    code = ""
    with contextlib.suppress(ValueError):
        body = response.json()
        if isinstance(body, dict):
            code = str(body.get("error", ""))
    # The status and Google's error code only: never the body, which could
    # echo parts of the assertion.
    logger.warning("google token grant failed: {} {}", response.status_code, code)
    if code in {"invalid_grant", "invalid_client", "unauthorized_client"}:
        return GoogleApiError(
            "Google rejected the service-account key (it may be deleted or disabled)"
        )
    if response.status_code == 429:
        return GoogleApiError("Google is rate limiting sign-in; please try again")
    return GoogleApiError(f"Google sign-in failed (HTTP {response.status_code})")

"""Where Google access tokens come from.

Calendar and Sheets calls only need ``await source.access_token(scopes)``;
which grant produced the token is the source's business. Service accounts
are implemented here (JWT-bearer grant, RFC 7523); OAuth2 connections will
add a second implementation of :class:`GoogleCredentialsSource`.
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

from fallcha_tools.providers.google_calendar.errors import GoogleApiError
from fallcha_tools.providers.google_calendar.settings import ServiceAccountKey

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

    def invalidate(self, key: CacheKey) -> None:
        self._tokens.pop(key, None)

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

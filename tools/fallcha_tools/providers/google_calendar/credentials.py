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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger

from fallcha_tools.providers.google_calendar.errors import GoogleApiError
from fallcha_tools.providers.google_calendar.settings import ServiceAccountKey

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ASSERTION_LIFETIME = timedelta(hours=1)
# A cached token is replaced this long before Google says it expires.
REFRESH_MARGIN = timedelta(minutes=5)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class GoogleCredentialsSource(Protocol):
    """Supplies a bearer token for Google APIs, for one connection."""

    async def access_token(self, scopes: Sequence[str]) -> str: ...


@dataclass(frozen=True, slots=True)
class CachedToken:
    token: str
    expires_at: datetime


CacheKey = tuple[uuid.UUID, str, tuple[str, ...]]


class TokenCache:
    """Process-wide token cache with single-flight minting per key.

    Keys include the connection and the scope set, so connections never share
    tokens and a narrower-scoped token is never reused for a wider call.
    """

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._tokens: dict[CacheKey, CachedToken] = {}
        self._locks: dict[CacheKey, asyncio.Lock] = {}

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
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            token = self._fresh(key)  # another task may have minted meanwhile
            if token is not None:
                return token
            minted = await mint()
            self._prune()
            self._tokens[key] = minted
            return minted.token

    def _prune(self) -> None:
        now = self._clock()
        for stale in [k for k, v in self._tokens.items() if v.expires_at <= now]:
            del self._tokens[stale]
            self._locks.pop(stale, None)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_assertion(
    key: ServiceAccountKey, scopes: Sequence[str], issued_at: datetime
) -> str:
    """A signed RS256 JWT asserting ``key.client_email`` for ``scopes``."""
    header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
    if key.private_key_id:
        header["kid"] = key.private_key_id
    iat = int(issued_at.timestamp())
    claims = {
        "iss": key.client_email,
        "scope": " ".join(scopes),
        "aud": GOOGLE_TOKEN_URL,
        "iat": iat,
        "exp": iat + int(ASSERTION_LIFETIME.total_seconds()),
    }
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode())
        for part in (header, claims)
    )
    signature = key.signer().sign(
        signing_input.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{signing_input}.{_b64url(signature)}"


@dataclass(frozen=True, slots=True)
class ServiceAccountCredentials:
    """Mints tokens for one connection's service account, via the cache."""

    connection_id: uuid.UUID
    key: ServiceAccountKey
    http: httpx.AsyncClient
    cache: TokenCache
    timeout: httpx.Timeout
    clock: Clock = utc_now

    async def access_token(self, scopes: Sequence[str]) -> str:
        wanted = tuple(sorted(scopes))
        cache_key: CacheKey = (self.connection_id, self.key.client_email, wanted)
        return await self.cache.get_or_mint(cache_key, lambda: self._mint(wanted))

    async def _mint(self, scopes: tuple[str, ...]) -> CachedToken:
        now = self.clock()
        assertion = sign_assertion(self.key, scopes, now)
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

"""Fixed-window rate limiting shared across API workers (Redis)."""

from datetime import timedelta
from functools import lru_cache
from typing import Protocol

import redis.asyncio as aioredis
from loguru import logger

from api.constants import REDIS_URL


class RateLimiter(Protocol):
    async def allow(self, key: str, *, limit: int, window: timedelta) -> bool:
        """Count one attempt against ``key``; False once ``limit`` attempts
        were made in the current ``window``."""
        ...


class RedisRateLimiter:
    """INCR + EXPIRE fixed window. Fails open: a Redis outage must not lock
    people out of login-adjacent flows, so errors allow the attempt."""

    _PREFIX = "ratelimit:"

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: aioredis.Redis | None = None

    def _redis(self) -> aioredis.Redis:
        if self._client is None:
            # redis-py ships from_url without annotations.
            self._client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._url, decode_responses=True
            )
        return self._client

    async def allow(self, key: str, *, limit: int, window: timedelta) -> bool:
        name = f"{self._PREFIX}{key}"
        try:
            client = self._redis()
            count = int(await client.incr(name))
            if count == 1:
                await client.expire(name, int(window.total_seconds()))
            return count <= limit
        except Exception:  # noqa: BLE001 - fail open, see class docstring
            logger.warning(f"Rate limiter unavailable; allowing {key}")
            return True


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    """Process-wide limiter (FastAPI dependency)."""
    return RedisRateLimiter(REDIS_URL)


__all__ = ["RateLimiter", "RedisRateLimiter", "get_rate_limiter"]

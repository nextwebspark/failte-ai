"""In-memory stand-in for the Redis rate limiter."""

from collections import Counter
from datetime import timedelta


class InMemoryRateLimiter:
    """Counts attempts per key and ignores the window (tests run instantly)."""

    def __init__(self) -> None:
        self.hits: Counter[str] = Counter()

    async def allow(self, key: str, *, limit: int, window: timedelta) -> bool:
        self.hits[key] += 1
        return self.hits[key] <= limit

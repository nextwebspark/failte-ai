"""In-memory stand-in for the Redis verification code store."""

from dataclasses import dataclass, field

from api.errors.account import VerificationCodeUnavailableError
from api.services.auth.verification_codes import (
    HOURLY_FAILURE_LIMIT,
    MAX_ATTEMPTS_PER_CODE,
    CodeCheck,
)


@dataclass
class _Live:
    code: str
    attempts: int = 0


@dataclass
class InMemoryVerificationCodeStore:
    """Same rules as the Redis store, minus time: codes never expire on their
    own (call :meth:`expire`) and only the hourly failure limit applies.
    Codes are sequential so tests can tell them apart. Set ``down`` to
    simulate a Redis outage."""

    live: dict[int, _Live] = field(default_factory=dict)
    failures: dict[int, int] = field(default_factory=dict)
    down: bool = False
    _next: int = 100000

    def _require_up(self) -> None:
        if self.down:
            raise VerificationCodeUnavailableError()

    async def issue(self, user_id: int) -> str:
        self._require_up()
        self._next += 1
        code = str(self._next)
        self.live[user_id] = _Live(code)
        return code

    async def has_live_code(self, user_id: int) -> bool:
        self._require_up()
        return user_id in self.live

    async def is_locked(self, user_id: int) -> bool:
        self._require_up()
        return self.failures.get(user_id, 0) >= HOURLY_FAILURE_LIMIT

    async def check(self, user_id: int, code: str) -> CodeCheck:
        if await self.is_locked(user_id):
            return CodeCheck.LOCKED
        live = self.live.get(user_id)
        if live is None:
            return CodeCheck.MISSING
        if live.code == code:
            del self.live[user_id]
            return CodeCheck.VERIFIED
        self.failures[user_id] = self.failures.get(user_id, 0) + 1
        live.attempts += 1
        if live.attempts >= MAX_ATTEMPTS_PER_CODE:
            del self.live[user_id]
        return CodeCheck.WRONG

    def expire(self, user_id: int) -> None:
        self.live.pop(user_id, None)

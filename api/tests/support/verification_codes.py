"""In-memory stand-in for the Redis verification code store."""

from dataclasses import dataclass, field

from api.services.auth.verification_codes import (
    MAX_ATTEMPTS_PER_CODE,
    MAX_FAILURES_PER_WINDOW,
    CodeCheck,
)


@dataclass
class _Live:
    code: str
    attempts: int = 0


@dataclass
class InMemoryVerificationCodeStore:
    """Same rules as the Redis store, minus time: codes never expire on their
    own; call :meth:`expire` to simulate it. Codes are sequential so tests can
    tell them apart."""

    live: dict[int, _Live] = field(default_factory=dict)
    failures: dict[int, int] = field(default_factory=dict)
    _next: int = 100000

    async def issue(self, user_id: int) -> str:
        self._next += 1
        code = str(self._next)
        self.live[user_id] = _Live(code)
        return code

    async def has_live_code(self, user_id: int) -> bool:
        return user_id in self.live

    async def check(self, user_id: int, code: str) -> CodeCheck:
        if self.failures.get(user_id, 0) >= MAX_FAILURES_PER_WINDOW:
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

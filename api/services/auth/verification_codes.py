"""Six-digit email verification codes (Redis).

A code is short enough to type, so it is only safe with a tight guess budget:

* one live code per user, valid for :data:`CODE_TTL`; issuing a new one
  replaces it;
* each code dies after :data:`MAX_ATTEMPTS_PER_CODE` wrong guesses;
* :data:`MAX_FAILURES_PER_WINDOW` wrong guesses per user per
  :data:`FAILURE_WINDOW`, across resends, lock verification until the window
  ends (otherwise resending would reset the budget).

Only an HMAC of ``user_id:code`` is stored, keyed from the server secret, so a
leaked Redis snapshot doesn't hand out codes. Unlike the rate limiter, this
store fails closed: a Redis error raises :class:`VerificationCodeUnavailableError`.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Protocol

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from api.constants import OSS_JWT_SECRET, REDIS_URL
from api.errors.account import VerificationCodeUnavailableError

CODE_DIGITS = 6
CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS_PER_CODE = 5
MAX_FAILURES_PER_WINDOW = 15
FAILURE_WINDOW = timedelta(hours=1)

_KEY_LABEL = b"email-verification-code"


class CodeCheck(StrEnum):
    VERIFIED = "verified"
    WRONG = "wrong"
    # No live code: never issued, expired, used, or burned by wrong guesses.
    MISSING = "missing"
    # Too many wrong guesses across codes; wait for the window to end.
    LOCKED = "locked"


class VerificationCodeStore(Protocol):
    async def issue(self, user_id: int) -> str:
        """Return a new code for ``user_id``, replacing any live one."""
        ...

    async def has_live_code(self, user_id: int) -> bool: ...

    async def check(self, user_id: int, code: str) -> CodeCheck:
        """Spend one attempt on ``code``; a verified code is consumed."""
        ...


def new_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def derive_code_key(secret: str) -> bytes:
    """Subkey of the server secret used only for code digests."""
    return hmac.new(secret.encode(), _KEY_LABEL, hashlib.sha256).digest()


def code_digest(key: bytes, user_id: int, code: str) -> str:
    return hmac.new(key, f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


# KEYS[1] code hash, KEYS[2] failure counter.
# ARGV: digest, max attempts per code, max failures per window, window seconds.
# Returns 1 verified, 0 wrong, -1 missing, -2 locked.
_CHECK_SCRIPT = """
local failures = tonumber(redis.call('GET', KEYS[2]) or '0')
if failures >= tonumber(ARGV[3]) then
  return -2
end
local stored = redis.call('HGET', KEYS[1], 'digest')
if not stored then
  return -1
end
if stored == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
if redis.call('INCR', KEYS[2]) == 1 then
  redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
end
if redis.call('HINCRBY', KEYS[1], 'attempts', 1) >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
end
return 0
"""

_RESULTS = {
    1: CodeCheck.VERIFIED,
    0: CodeCheck.WRONG,
    -1: CodeCheck.MISSING,
    -2: CodeCheck.LOCKED,
}


class RedisVerificationCodeStore:
    _CODE_PREFIX = "email-code:"
    _FAILURE_PREFIX = "email-code-failures:"

    def __init__(self, url: str, *, key: bytes) -> None:
        self._url = url
        self._key = key
        self._client: aioredis.Redis | None = None

    def _redis(self) -> aioredis.Redis:
        if self._client is None:
            # redis-py ships from_url without annotations.
            self._client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._url, decode_responses=True
            )
        return self._client

    async def issue(self, user_id: int) -> str:
        code = new_code()
        name = f"{self._CODE_PREFIX}{user_id}"
        try:
            async with self._redis().pipeline(transaction=True) as pipe:
                pipe.hset(
                    name,
                    mapping={
                        "digest": code_digest(self._key, user_id, code),
                        "attempts": 0,
                    },
                )
                pipe.expire(name, int(CODE_TTL.total_seconds()))
                await pipe.execute()
        except RedisError as exc:
            raise VerificationCodeUnavailableError() from exc
        return code

    async def has_live_code(self, user_id: int) -> bool:
        try:
            return bool(await self._redis().exists(f"{self._CODE_PREFIX}{user_id}"))
        except RedisError as exc:
            raise VerificationCodeUnavailableError() from exc

    async def check(self, user_id: int, code: str) -> CodeCheck:
        try:
            result = await self._redis().eval(  # type: ignore[misc]
                _CHECK_SCRIPT,
                2,
                f"{self._CODE_PREFIX}{user_id}",
                f"{self._FAILURE_PREFIX}{user_id}",
                code_digest(self._key, user_id, code),
                str(MAX_ATTEMPTS_PER_CODE),
                str(MAX_FAILURES_PER_WINDOW),
                str(int(FAILURE_WINDOW.total_seconds())),
            )
        except RedisError as exc:
            raise VerificationCodeUnavailableError() from exc
        return _RESULTS[int(result)]


@lru_cache(maxsize=1)
def get_verification_code_store() -> VerificationCodeStore:
    """Process-wide store (FastAPI dependency)."""
    return RedisVerificationCodeStore(REDIS_URL, key=derive_code_key(OSS_JWT_SECRET))


__all__ = [
    "CODE_DIGITS",
    "CODE_TTL",
    "CodeCheck",
    "RedisVerificationCodeStore",
    "VerificationCodeStore",
    "get_verification_code_store",
    "new_code",
]

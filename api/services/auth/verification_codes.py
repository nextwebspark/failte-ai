"""Six-digit email verification codes (Redis).

A code is short enough to type, so it is only safe with a tight guess budget:

* one live code per user, valid for :data:`CODE_TTL`; issuing a new one
  replaces it;
* each code dies after :data:`MAX_ATTEMPTS_PER_CODE` wrong guesses;
* wrong guesses per user are also counted across codes (otherwise resending
  would reset the budget): :data:`HOURLY_FAILURE_LIMIT` per hour and
  :data:`LONG_FAILURE_LIMIT` per :data:`LONG_FAILURE_WINDOW` lock
  verification. The long window bounds what a patient guesser gets over an
  invitation's lifetime to a fraction of a percent; a locked-out owner
  verifies by resetting their password instead.

Only an HMAC of ``user_id:code`` is stored, keyed from the server secret, so a
leaked Redis snapshot doesn't hand out codes. Unlike the rate limiter, this
store fails closed: a Redis error raises :class:`VerificationCodeUnavailableError`.
Keys share a ``{user_id}`` hash tag so the script also runs on Redis Cluster.
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
HOURLY_FAILURE_LIMIT = 15
HOURLY_FAILURE_WINDOW = timedelta(hours=1)
LONG_FAILURE_LIMIT = 50
LONG_FAILURE_WINDOW = timedelta(days=30)
_REDIS_TIMEOUT_SECONDS = 3

_KEY_LABEL = b"email-verification-code"


class CodeCheck(StrEnum):
    VERIFIED = "verified"
    WRONG = "wrong"
    # No live code: never issued, expired, used, or burned by wrong guesses.
    MISSING = "missing"
    # Too many wrong guesses across codes; wait, or reset the password.
    LOCKED = "locked"


class VerificationCodeStore(Protocol):
    async def issue(self, user_id: int) -> str:
        """Return a new code for ``user_id``, replacing any live one."""
        ...

    async def has_live_code(self, user_id: int) -> bool: ...

    async def is_locked(self, user_id: int) -> bool:
        """True while wrong guesses have locked verification for the user."""
        ...

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


# KEYS[1] code hash, KEYS[2] hourly failures, KEYS[3] long-window failures.
# ARGV: digest, max attempts per code, hourly limit, hourly window seconds,
# long limit, long window seconds.
# Returns 1 verified, 0 wrong, -1 missing, -2 locked.
_CHECK_SCRIPT = """
if tonumber(redis.call('GET', KEYS[2]) or '0') >= tonumber(ARGV[3])
   or tonumber(redis.call('GET', KEYS[3]) or '0') >= tonumber(ARGV[5]) then
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
if redis.call('INCR', KEYS[3]) == 1 then
  redis.call('EXPIRE', KEYS[3], tonumber(ARGV[6]))
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


def _code_key(user_id: int) -> str:
    return f"email-code:{{{user_id}}}"


def _hourly_failures_key(user_id: int) -> str:
    return f"email-code-failures-1h:{{{user_id}}}"


def _long_failures_key(user_id: int) -> str:
    return f"email-code-failures-30d:{{{user_id}}}"


class RedisVerificationCodeStore:
    def __init__(self, url: str, *, key: bytes) -> None:
        self._url = url
        self._key = key
        self._client: aioredis.Redis | None = None

    def _redis(self) -> aioredis.Redis:
        if self._client is None:
            # redis-py ships from_url without annotations. Timeouts keep a hung
            # Redis from stalling login (it fails closed instead).
            self._client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._url,
                decode_responses=True,
                socket_timeout=_REDIS_TIMEOUT_SECONDS,
                socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            )
        return self._client

    async def issue(self, user_id: int) -> str:
        code = new_code()
        name = _code_key(user_id)
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
            return bool(await self._redis().exists(_code_key(user_id)))
        except RedisError as exc:
            raise VerificationCodeUnavailableError() from exc

    async def is_locked(self, user_id: int) -> bool:
        try:
            hourly, long = await self._redis().mget(
                _hourly_failures_key(user_id), _long_failures_key(user_id)
            )
        except RedisError as exc:
            raise VerificationCodeUnavailableError() from exc
        return (
            int(hourly or 0) >= HOURLY_FAILURE_LIMIT
            or int(long or 0) >= LONG_FAILURE_LIMIT
        )

    async def check(self, user_id: int, code: str) -> CodeCheck:
        try:
            result = await self._redis().eval(  # type: ignore[misc]
                _CHECK_SCRIPT,
                3,
                _code_key(user_id),
                _hourly_failures_key(user_id),
                _long_failures_key(user_id),
                code_digest(self._key, user_id, code),
                str(MAX_ATTEMPTS_PER_CODE),
                str(HOURLY_FAILURE_LIMIT),
                str(int(HOURLY_FAILURE_WINDOW.total_seconds())),
                str(LONG_FAILURE_LIMIT),
                str(int(LONG_FAILURE_WINDOW.total_seconds())),
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
    "HOURLY_FAILURE_LIMIT",
    "LONG_FAILURE_LIMIT",
    "MAX_ATTEMPTS_PER_CODE",
    "CodeCheck",
    "RedisVerificationCodeStore",
    "VerificationCodeStore",
    "get_verification_code_store",
    "new_code",
]

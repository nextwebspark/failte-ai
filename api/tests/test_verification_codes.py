"""Redis verification code store (real Redis for the Lua paths) and the
verification email."""

import os
import uuid
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from api.errors.account import VerificationCodeUnavailableError
from api.services.auth.verification_codes import (
    CODE_TTL,
    HOURLY_FAILURE_LIMIT,
    LONG_FAILURE_LIMIT,
    LONG_FAILURE_WINDOW,
    MAX_ATTEMPTS_PER_CODE,
    CodeCheck,
    RedisVerificationCodeStore,
    code_digest,
    derive_code_key,
    new_code,
)
from api.services.email.templates import verification_code_message

requires_redis = pytest.mark.skipif(
    "REDIS_URL" not in os.environ,
    reason="Requires Redis (set REDIS_URL via .env.test)",
)

KEY = derive_code_key("test-secret")


def _user_id() -> int:
    # Far above real ids so parallel runs and leftovers never collide.
    return 10**9 + uuid.uuid4().int % 10**9


@pytest.fixture
async def store():
    store = RedisVerificationCodeStore(os.environ["REDIS_URL"], key=KEY)
    yield store
    await store._redis().aclose()


def _keys(user_id: int) -> tuple[str, str, str]:
    # One {user_id} hash tag, so the script's keys share a cluster slot.
    return (
        f"email-code:{{{user_id}}}",
        f"email-code-failures-1h:{{{user_id}}}",
        f"email-code-failures-30d:{{{user_id}}}",
    )


async def _cleanup(store: RedisVerificationCodeStore, user_id: int) -> None:
    await store._redis().delete(*_keys(user_id))


async def _fail(store: RedisVerificationCodeStore, user_id: int, times: int) -> None:
    """Spend ``times`` wrong guesses, issuing new codes as they burn out."""
    spent = 0
    while spent < times:
        code = await store.issue(user_id)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(min(MAX_ATTEMPTS_PER_CODE, times - spent)):
            assert await store.check(user_id, wrong) is CodeCheck.WRONG
            spent += 1


def test_new_code_is_six_digits():
    codes = {new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150


def test_digest_is_keyed_and_bound_to_the_user():
    assert code_digest(KEY, 1, "123456") != code_digest(KEY, 2, "123456")
    assert code_digest(KEY, 1, "123456") != code_digest(
        derive_code_key("other-secret"), 1, "123456"
    )


@requires_redis
async def test_issue_check_consume(store):
    user_id = _user_id()
    try:
        code = await store.issue(user_id)
        assert await store.has_live_code(user_id)
        stored = await store._redis().hgetall(_keys(user_id)[0])
        assert stored and code not in stored.values()  # only the digest is kept
        ttl = await store._redis().ttl(_keys(user_id)[0])
        assert 0 < ttl <= CODE_TTL.total_seconds()

        assert await store.check(user_id, code) is CodeCheck.VERIFIED
        assert not await store.has_live_code(user_id)
        assert await store.check(user_id, code) is CodeCheck.MISSING
    finally:
        await _cleanup(store, user_id)


@requires_redis
async def test_reissue_replaces_and_resets_attempts(store):
    user_id = _user_id()
    try:
        first = await store.issue(user_id)
        wrong = "000000" if first != "000000" else "111111"
        for _ in range(MAX_ATTEMPTS_PER_CODE - 1):
            assert await store.check(user_id, wrong) is CodeCheck.WRONG
        second = await store.issue(user_id)
        if first != second:
            assert await store.check(user_id, first) is CodeCheck.WRONG
        assert await store.check(user_id, second) is CodeCheck.VERIFIED
    finally:
        await _cleanup(store, user_id)


@requires_redis
async def test_code_is_burned_after_max_attempts(store):
    user_id = _user_id()
    try:
        code = await store.issue(user_id)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(MAX_ATTEMPTS_PER_CODE):
            assert await store.check(user_id, wrong) is CodeCheck.WRONG
        assert not await store.has_live_code(user_id)
        assert await store.check(user_id, code) is CodeCheck.MISSING
    finally:
        await _cleanup(store, user_id)


@requires_redis
async def test_hourly_failures_lock_across_reissues(store):
    user_id = _user_id()
    try:
        await _fail(store, user_id, HOURLY_FAILURE_LIMIT)
        assert await store.is_locked(user_id)
        fresh = await store.issue(user_id)
        assert await store.check(user_id, fresh) is CodeCheck.LOCKED
        assert 0 < await store._redis().ttl(_keys(user_id)[1]) <= 3600
    finally:
        await _cleanup(store, user_id)


@requires_redis
async def test_long_window_caps_total_guesses(store):
    user_id = _user_id()
    hourly, long_window = _keys(user_id)[1:]
    try:
        await _fail(store, user_id, HOURLY_FAILURE_LIMIT - 1)
        assert not await store.is_locked(user_id)
        # The hour has passed; the long-window count stays.
        await store._redis().delete(hourly)
        await store._redis().set(long_window, LONG_FAILURE_LIMIT - 1, keepttl=True)
        assert not await store.is_locked(user_id)
        await _fail(store, user_id, 1)
        assert await store.is_locked(user_id)
        fresh = await store.issue(user_id)
        assert await store.check(user_id, fresh) is CodeCheck.LOCKED
        ttl = await store._redis().ttl(long_window)
        assert 0 < ttl <= LONG_FAILURE_WINDOW.total_seconds()
    finally:
        await _cleanup(store, user_id)


async def test_redis_errors_fail_closed():
    store = RedisVerificationCodeStore("redis://unused", key=KEY)
    client = AsyncMock()
    client.eval.side_effect = RedisConnectionError("down")
    client.exists.side_effect = RedisConnectionError("down")
    client.mget.side_effect = RedisConnectionError("down")
    store._client = client

    with pytest.raises(VerificationCodeUnavailableError):
        await store.check(1, "123456")
    with pytest.raises(VerificationCodeUnavailableError):
        await store.has_live_code(1)
    with pytest.raises(VerificationCodeUnavailableError):
        await store.is_locked(1)


def test_verification_email_shows_the_code_without_a_link():
    message = verification_code_message(
        to="a@example.com", code="012345", expires_in_minutes=15
    )
    assert message.subject.startswith("012345 is your ")
    assert "012345" in message.text and "012345" in message.html
    assert "15 minutes" in message.text
    assert "href=" not in message.html

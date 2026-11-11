"""Shared recording links: the token, expiry, revoking, and the public
endpoints' answers. No database: the DB client is replaced by a fake."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routes import recording_shares as routes
from api.services.calls import recording_shares as shares_mod
from api.services.calls.recording_shares import (
    MAX_SIGNED_URL_SECONDS,
    ShareExpiry,
    ShareState,
    active_shares,
    add_share,
    find_share,
    hash_secret,
    new_share,
    new_token,
    parse_token,
    prune,
    revoke,
    share_state,
    signed_url_seconds,
)

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def _share(expiry=ShareExpiry.WEEK, now=NOW, token_hash="h"):
    return new_share(
        token_hash=token_hash,
        expiry=expiry,
        user_id=7,
        name="Maria Keane",
        email="maria@example.com",
        now=now,
    )


# ---------- Tokens ----------


def test_token_carries_the_call_id_and_a_long_random_secret():
    token, token_hash = new_token(123)
    run_id, secret = parse_token(token)

    assert run_id == 123
    assert len(secret) == 43  # 32 random bytes, base64url
    assert token_hash == hash_secret(secret)
    assert secret not in token_hash  # only the hash is stored
    assert new_token(123)[0] != token


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "123",
        "123.",
        "x.AAAA",
        "123.short",
        "-1." + "A" * 43,
        "1." + "A" * 42 + "!",
    ],
)
def test_malformed_tokens_are_rejected(bad):
    assert parse_token(bad) is None


def test_find_share_matches_only_the_right_secret():
    token, token_hash = new_token(5)
    _, secret = parse_token(token)
    other = _share(token_hash=hash_secret("someone-else"))
    mine = _share(token_hash=token_hash)

    assert find_share([other, mine], secret) is mine
    assert find_share([other], secret) is None
    assert find_share([{"token_hash": None}, {}], secret) is None


# ---------- Expiry ----------


def test_expiry_choices_and_states():
    day = _share(ShareExpiry.DAY)
    week = _share(ShareExpiry.WEEK)

    assert datetime.fromisoformat(day["expires_at"]) == NOW + timedelta(hours=24)
    assert datetime.fromisoformat(week["expires_at"]) == NOW + timedelta(days=7)
    assert share_state(day, NOW + timedelta(hours=23)) == ShareState.ACTIVE
    assert share_state(day, NOW + timedelta(hours=24)) == ShareState.EXPIRED
    assert share_state(week, NOW + timedelta(days=6)) == ShareState.ACTIVE
    assert share_state({"expires_at": "not a date"}, NOW) == ShareState.EXPIRED


def test_created_by_falls_back_to_the_email_name():
    share = new_share(
        token_hash="h",
        expiry=ShareExpiry.DAY,
        user_id=1,
        name=" ",
        email="sean@x.ie",
        now=NOW,
    )
    assert share["created_by"] == "sean"
    assert share["revoked_at"] is None


def test_signed_url_never_outlives_the_link():
    share = _share(ShareExpiry.DAY)

    assert signed_url_seconds(share, NOW) == MAX_SIGNED_URL_SECONDS
    assert signed_url_seconds(share, NOW + timedelta(hours=23, minutes=50)) == 600


# ---------- Revoke and the stored list ----------


def test_revoke_turns_one_link_off_and_keeps_the_rest():
    a, b = _share(), _share()
    later = NOW + timedelta(minutes=5)
    result = revoke([a, b], a["id"], later)

    assert share_state(result[0], later) == ShareState.REVOKED
    assert share_state(result[1], later) == ShareState.ACTIVE
    assert [s["id"] for s in active_shares(result, later)] == [b["id"]]
    assert revoke([a, b], "nope", later) is None
    # Revoking again keeps the first time.
    assert (
        revoke(result, a["id"], later + timedelta(hours=1))[0]["revoked_at"]
        == later.isoformat()
    )


def test_active_list_hides_hashes_and_ended_links():
    live = _share()
    expired = _share(ShareExpiry.DAY, now=NOW - timedelta(days=2))
    listed = active_shares([live, expired], NOW)

    assert listed == [
        {
            "id": live["id"],
            "created_at": live["created_at"],
            "expires_at": live["expires_at"],
            "created_by": "Maria Keane",
        }
    ]


def test_prune_drops_links_that_ended_long_ago():
    old = _share(ShareExpiry.DAY, now=NOW - timedelta(days=40))
    recent_expired = _share(ShareExpiry.DAY, now=NOW - timedelta(days=3))
    live = _share()

    kept = prune([old, recent_expired, live], NOW)
    assert old not in kept and recent_expired in kept and live in kept


def test_add_share_caps_the_list():
    many = [_share(now=NOW - timedelta(minutes=i)) for i in range(40)]
    assert len(add_share(many, _share(), NOW)) == shares_mod.MAX_SHARES


# ---------- Endpoints ----------


class FakeDB:
    def __init__(self, recording_url="recordings/1/abc/call.wav"):
        self.call = {
            "id": 42,
            "created_at": NOW - timedelta(hours=1),
            "recording_url": recording_url,
            "storage_backend": "minio",
            "annotations": {},
            "usage_info": {"call_duration_seconds": 131.6},
            "initial_context": {"caller_number": "+353871234567"},
            "template_context_variables": {"business_name": "Bia Bistro"},
            "extra": {},
            "organization_id": 3,
            "organization_name": "Bia Ltd",
        }

    async def change_recording_shares(self, organization_id, run_id, change):
        if organization_id != 3 or run_id != 42:
            return None
        result = change(
            {"recording_url": self.call["recording_url"]},
            list(self.call["annotations"].get("shares", [])),
        )
        if result is None:
            return None
        self.call["annotations"]["shares"] = result
        return result

    async def get_recording_shares(self, organization_id, run_id):
        if organization_id != 3 or run_id != 42:
            return None
        return {"recording_url": self.call["recording_url"]}, self.call[
            "annotations"
        ].get("shares", [])

    async def get_shared_call(self, run_id):
        return dict(self.call) if run_id == 42 else None


class FakeStorage:
    def __init__(self):
        self.asked = []

    async def aget_signed_url(self, file_path, expiration, force_inline):
        self.asked.append((file_path, expiration, force_inline))
        return f"https://storage.example/{file_path}?sig=1"


@pytest.fixture
def fake(monkeypatch):
    db = FakeDB()
    storage = FakeStorage()
    monkeypatch.setattr(routes, "db_client", db)
    monkeypatch.setattr(routes, "get_storage_for_backend", lambda _backend: storage)

    async def zone(_org):
        return "Europe/Dublin"

    monkeypatch.setattr(routes, "_timezone", zone)
    return SimpleNamespace(db=db, storage=storage)


MEMBER = SimpleNamespace(
    organization_id=3, user=SimpleNamespace(id=7, name="Maria Keane", email="m@x.ie")
)
OTHER_ORG = SimpleNamespace(
    organization_id=9, user=SimpleNamespace(id=8, name="Eve", email="e@x.ie")
)


def _token(url: str) -> str:
    return url.rsplit("/listen/", 1)[1]


@pytest.mark.asyncio
async def test_share_round_trip(fake):
    created = await routes.create_recording_share(
        42, MEMBER, routes.CreateRecordingShareRequest(expires_in="24h")
    )
    token = _token(created.url)
    assert token.startswith("42.")
    assert created.expires_at - created.created_at == timedelta(hours=24)
    # The token itself is never stored.
    assert token.split(".", 1)[1] not in str(fake.db.call["annotations"])

    listed = await routes.list_recording_shares(42, MEMBER)
    assert [s.id for s in listed.shares] == [created.id]

    response = SimpleNamespace(headers={})
    info = await routes.shared_recording_info(token, response)
    assert info.status == "active"
    assert info.business_name == "Bia Bistro"
    assert info.duration_seconds == 132
    assert "caller" not in info.model_dump_json()
    assert "+353" not in info.model_dump_json()
    assert response.headers["Cache-Control"] == "no-store"

    redirect = await routes.play_shared_recording(token)
    assert redirect.status_code == 302
    assert redirect.headers["location"].startswith("https://storage.example/")
    ((_path, expiration, inline),) = fake.storage.asked
    assert expiration <= MAX_SIGNED_URL_SECONDS and inline is True


@pytest.mark.asyncio
async def test_default_expiry_is_seven_days(fake):
    created = await routes.create_recording_share(42, MEMBER, None)
    assert created.expires_at - created.created_at == timedelta(days=7)


@pytest.mark.asyncio
async def test_revoked_link_stops_at_once(fake):
    created = await routes.create_recording_share(42, MEMBER, None)
    token = _token(created.url)

    await routes.revoke_recording_share(42, created.id, MEMBER)

    assert (await routes.list_recording_shares(42, MEMBER)).shares == []
    info = await routes.shared_recording_info(token, SimpleNamespace(headers={}))
    assert info.status == "revoked" and info.business_name is None
    with pytest.raises(HTTPException) as err:
        await routes.play_shared_recording(token)
    assert err.value.status_code == 410
    assert fake.storage.asked == []


@pytest.mark.asyncio
async def test_expired_link_says_so_and_plays_nothing(fake, monkeypatch):
    created = await routes.create_recording_share(42, MEMBER, None)
    token = _token(created.url)
    stored = fake.db.call["annotations"]["shares"][0]
    stored["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    info = await routes.shared_recording_info(token, SimpleNamespace(headers={}))
    assert info.status == "expired" and info.called_at is None
    with pytest.raises(HTTPException) as err:
        await routes.play_shared_recording(token)
    assert err.value.status_code == 410


@pytest.mark.asyncio
async def test_purged_recording_is_no_longer_available(fake):
    created = await routes.create_recording_share(42, MEMBER, None)
    token = _token(created.url)
    fake.db.call["recording_url"] = None

    info = await routes.shared_recording_info(token, SimpleNamespace(headers={}))
    assert info.status == "unavailable"
    with pytest.raises(HTTPException) as err:
        await routes.play_shared_recording(token)
    assert err.value.status_code == 410

    # Retention also clears the links: then it's an unknown link.
    fake.db.call["annotations"] = {}
    with pytest.raises(HTTPException) as err:
        await routes.shared_recording_info(token, SimpleNamespace(headers={}))
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_wrong_or_made_up_tokens_get_nothing(fake):
    await routes.create_recording_share(42, MEMBER, None)
    for token in ["42." + "A" * 43, "nonsense", "43." + "B" * 43]:
        with pytest.raises(HTTPException) as err:
            await routes.play_shared_recording(token)
        assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_other_organizations_cannot_share_list_or_revoke(fake):
    with pytest.raises(HTTPException) as err:
        await routes.create_recording_share(42, OTHER_ORG, None)
    assert err.value.status_code == 404

    created = await routes.create_recording_share(42, MEMBER, None)
    with pytest.raises(HTTPException):
        await routes.list_recording_shares(42, OTHER_ORG)
    with pytest.raises(HTTPException):
        await routes.revoke_recording_share(42, created.id, OTHER_ORG)
    assert len((await routes.list_recording_shares(42, MEMBER)).shares) == 1


@pytest.mark.asyncio
async def test_a_call_without_a_recording_cannot_be_shared(fake):
    fake.db.call["recording_url"] = None
    with pytest.raises(HTTPException) as err:
        await routes.create_recording_share(42, MEMBER, None)
    assert err.value.status_code == 409
    assert fake.db.call["annotations"] == {}

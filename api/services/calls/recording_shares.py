"""Share one call's recording with an expiring link.

A link is stored on the call itself, in ``annotations["shares"]`` (no table
of its own), as::

    {"id": "k3J...", "token_hash": "<sha256 hex>", "created_at": ISO,
     "expires_at": ISO, "created_by_user_id": 7, "created_by": "Maria",
     "revoked_at": ISO | None}

The link's token is ``<call id>.<secret>``. Only the secret's SHA-256 is
stored, so a copy of the database (or a backup) holds no working links; the
call id in front lets the public page find the call by its primary key
instead of searching every call's annotations. The secret is 32 random bytes
(256 bits), so guessing one is out of reach.

Expired and revoked entries are kept a while so the public page can say why
a link stopped working, then pruned. Retention scrubs ``annotations`` with the
rest of the call, so a purged call's links simply stop matching.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

SHARES_ANNOTATION = "shares"


class ShareExpiry(StrEnum):
    DAY = "24h"
    WEEK = "7d"


EXPIRY_DURATIONS: dict[ShareExpiry, timedelta] = {
    ShareExpiry.DAY: timedelta(hours=24),
    ShareExpiry.WEEK: timedelta(days=7),
}
DEFAULT_EXPIRY = ShareExpiry.WEEK

# Ended links are kept this long (to say "expired" or "turned off"), then dropped.
KEEP_ENDED = timedelta(days=30)
# At most this many links are kept on one call, newest first.
MAX_SHARES = 25

# Signed recording URLs handed to a listener last at most this long.
MAX_SIGNED_URL_SECONDS = 3600

_SECRET_BYTES = 32
_TOKEN = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{43})$")


class ShareState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def new_token(run_id: int) -> tuple[str, str]:
    """A fresh link token for a call, and the hash to store."""
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return f"{run_id}.{secret}", hash_secret(secret)


def parse_token(token: str) -> tuple[int, str] | None:
    """(call id, secret) from a link token, or None if it isn't one."""
    match = _TOKEN.match(token or "")
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def _when(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def share_state(share: dict[str, Any], now: datetime) -> ShareState:
    if share.get("revoked_at"):
        return ShareState.REVOKED
    expires = _when(share.get("expires_at"))
    if expires is None or expires <= now:
        return ShareState.EXPIRED
    return ShareState.ACTIVE


def stored_shares(annotations: dict[str, Any] | None) -> list[dict[str, Any]]:
    shares = (annotations or {}).get(SHARES_ANNOTATION)
    if not isinstance(shares, list):
        return []
    return [s for s in shares if isinstance(s, dict)]


def find_share(shares: Iterable[dict[str, Any]], secret: str) -> dict[str, Any] | None:
    """The stored link whose hash matches ``secret`` (compared in constant time)."""
    wanted = hash_secret(secret)
    found = None
    for share in shares:
        stored = share.get("token_hash")
        if isinstance(stored, str) and hmac.compare_digest(stored, wanted):
            found = share
    return found


def new_share(
    *,
    token_hash: str,
    expiry: ShareExpiry,
    user_id: int,
    name: str | None,
    email: str | None,
    now: datetime,
) -> dict[str, Any]:
    who = (name or "").strip() or (email or "").split("@")[0].strip() or None
    return {
        "id": secrets.token_urlsafe(9),
        "token_hash": token_hash,
        "created_at": now.isoformat(),
        "expires_at": (now + EXPIRY_DURATIONS[expiry]).isoformat(),
        "created_by_user_id": user_id,
        "created_by": who,
        "revoked_at": None,
    }


def prune(shares: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Drop links that ended long ago, and keep the newest MAX_SHARES."""
    kept = []
    for share in shares:
        state = share_state(share, now)
        ended = _when(share.get("revoked_at") or share.get("expires_at"))
        if state != ShareState.ACTIVE and (ended is None or now - ended > KEEP_ENDED):
            continue
        kept.append(share)
    kept.sort(key=lambda s: str(s.get("created_at") or ""), reverse=True)
    return kept[:MAX_SHARES]


def add_share(
    shares: list[dict[str, Any]], share: dict[str, Any], now: datetime
) -> list[dict[str, Any]]:
    return prune([share, *shares], now)


def revoke(
    shares: list[dict[str, Any]], share_id: str, now: datetime
) -> list[dict[str, Any]] | None:
    """The links with ``share_id`` turned off, or None if there's no such link.
    Revoking an ended link again changes nothing."""
    if not any(s.get("id") == share_id for s in shares):
        return None
    return [
        {**s, "revoked_at": now.isoformat()}
        if s.get("id") == share_id and not s.get("revoked_at")
        else s
        for s in shares
    ]


def active_shares(
    shares: Iterable[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """The links still working, newest first, without their hashes."""
    return [
        {
            "id": s.get("id"),
            "created_at": s.get("created_at"),
            "expires_at": s.get("expires_at"),
            "created_by": s.get("created_by"),
        }
        for s in sorted(
            shares, key=lambda s: str(s.get("created_at") or ""), reverse=True
        )
        if share_state(s, now) == ShareState.ACTIVE
    ]


def signed_url_seconds(share: dict[str, Any], now: datetime) -> int:
    """How long a signed recording URL may last: an hour at most, and never
    past the link's own expiry."""
    expires = _when(share.get("expires_at"))
    left = int((expires - now).total_seconds()) if expires else 0
    return max(1, min(MAX_SIGNED_URL_SECONDS, left))

"""Signed links in report emails: confirming an address and unsubscribing.

Both are HS256 JWTs under the server secret, each with its own audience so
one can never be used as the other. Neither carries the address itself, only
a short hash of it, so a forwarded link doesn't reveal who it was for.

* Confirm links expire after ``CONFIRM_TTL`` and are single use: they carry a
  nonce that is stored on the pending recipient and cleared once confirmed
  (or replaced when the email is resent, which retires the older link).
* Unsubscribe links last as long as old emails do (``UNSUBSCRIBE_TTL``) and
  name one recipient entry; removing it is idempotent.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

CONFIRM_TTL = timedelta(hours=48)
UNSUBSCRIBE_TTL = timedelta(days=400)

_CONFIRM_AUDIENCE = "lightmove-report-confirm"
_UNSUBSCRIBE_AUDIENCE = "lightmove-report-unsubscribe"


def email_hash(address: str) -> str:
    return hashlib.sha256(address.strip().casefold().encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RecipientClaim:
    organization_id: int
    recipient_id: str
    email_hash: str
    nonce: str | None = None

    def matches(self, address: str, nonce: str | None = None) -> bool:
        if not hmac.compare_digest(self.email_hash, email_hash(address)):
            return False
        if self.nonce is None:
            return True
        return nonce is not None and hmac.compare_digest(self.nonce, nonce)


def _encode(claims: dict, audience: str, ttl: timedelta, secret: str, now) -> str:
    issued = now or datetime.now(UTC)
    return jwt.encode(
        {**claims, "aud": audience, "iat": issued, "exp": issued + ttl},
        secret,
        algorithm="HS256",
    )


def _decode(token: str, audience: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience=audience)
    except jwt.PyJWTError:
        return None


def confirm_token(
    *,
    organization_id: int,
    recipient_id: str,
    address: str,
    nonce: str,
    secret: str,
    now: datetime | None = None,
) -> str:
    return _encode(
        {
            "org": organization_id,
            "rid": recipient_id,
            "eh": email_hash(address),
            "n": nonce,
        },
        _CONFIRM_AUDIENCE,
        CONFIRM_TTL,
        secret,
        now,
    )


def unsubscribe_token(
    *,
    organization_id: int,
    recipient_id: str,
    address: str,
    secret: str,
    now: datetime | None = None,
) -> str:
    return _encode(
        {"org": organization_id, "rid": recipient_id, "eh": email_hash(address)},
        _UNSUBSCRIBE_AUDIENCE,
        UNSUBSCRIBE_TTL,
        secret,
        now,
    )


def _claim(claims: dict | None, *, with_nonce: bool) -> RecipientClaim | None:
    if not claims:
        return None
    org, rid, eh = claims.get("org"), claims.get("rid"), claims.get("eh")
    nonce = claims.get("n")
    if not isinstance(org, int) or not isinstance(rid, str) or not isinstance(eh, str):
        return None
    if with_nonce and not isinstance(nonce, str):
        return None
    return RecipientClaim(org, rid, eh, nonce if with_nonce else None)


def read_confirm_token(token: str, secret: str) -> RecipientClaim | None:
    """The claim, or None when the link is forged, expired or malformed."""
    return _claim(_decode(token, _CONFIRM_AUDIENCE, secret), with_nonce=True)


def read_unsubscribe_token(token: str, secret: str) -> RecipientClaim | None:
    return _claim(_decode(token, _UNSUBSCRIBE_AUDIENCE, secret), with_nonce=False)

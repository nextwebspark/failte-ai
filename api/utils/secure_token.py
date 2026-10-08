"""Single-use secret tokens (invitations, email verification, password reset).

Only the SHA-256 digest is stored; the raw token goes to the recipient once.
"""

import hashlib
import secrets
from dataclasses import dataclass

_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class IssuedToken:
    raw: str
    digest: str


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token() -> IssuedToken:
    raw = secrets.token_urlsafe(_TOKEN_BYTES)
    return IssuedToken(raw=raw, digest=hash_token(raw))

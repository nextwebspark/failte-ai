"""Connection keys: random bearer tokens stored only as SHA-256 hashes."""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "ftk_"


def generate_connection_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_connection_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def looks_like_connection_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX) and 16 < len(value) <= 128

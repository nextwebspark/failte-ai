"""Operator-trusted internal service origins for the SaaS URL guard.

An origin is ``(scheme, host, port)``: trusting ``http://fallcha-tools:8000``
does not trust any other port or scheme on that host. Entries that name a
loopback/local host or an IP literal are refused (logged and ignored): a
trusted entry bypasses the private-address check, so it must name one
specific internal service, never a whole address.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from loguru import logger

Origin = tuple[str, str, int]

_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def origin_of(url: str) -> Origin | None:
    """``(scheme, host, port)`` of an absolute URL, else None."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    return scheme, host, port if port is not None else _DEFAULT_PORTS[scheme]


def _refusal(host: str) -> str | None:
    if host == "localhost" or host.endswith(".localhost"):
        return "is a loopback host"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return "is an IP literal"


def build_trusted_origins(
    entries: Iterable[str],
    *,
    tools_service_url: str | None,
    tools_internal_secret: str | None,
) -> frozenset[Origin]:
    """Parse ``TRUSTED_TOOL_HOSTS`` origins, plus the tools service origin
    when the tools service is configured (its secret is set)."""
    candidates = [e.strip() for e in entries if e.strip()]
    if tools_service_url and tools_internal_secret:
        candidates.append(tools_service_url)
    trusted: set[Origin] = set()
    for entry in candidates:
        origin = origin_of(entry)
        if origin is None:
            logger.warning(
                f"Ignoring trusted tool origin {entry!r}: expected scheme://host[:port]"
            )
            continue
        reason = _refusal(origin[1])
        if reason:
            logger.warning(f"Ignoring trusted tool origin {entry!r}: host {reason}")
            continue
        trusted.add(origin)
    return frozenset(trusted)

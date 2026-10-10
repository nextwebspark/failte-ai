"""Fetch URLs that a workspace configured, without SSRF.

A workspace can point a provider at any URL (e.g. its shop's sitemap), and
the service fetches it from inside the platform network. So every fetch:

* accepts only ``http``/``https`` URLs with a host, no credentials, and a
  standard port (80, 443, 8080, 8443);
* resolves the host and refuses it unless **every** address is public
  (no private, loopback, link-local, CGNAT, multicast, reserved or
  unspecified addresses, IPv4-mapped IPv6 included);
* follows redirects itself (at most 5), checking each hop the same way;
* re-checks at connect time: the transport's network backend resolves the
  host again and connects to the vetted IP, so DNS rebinding between the
  check and the connect cannot reach an internal address (TLS still uses
  the URL's hostname for SNI and certificate checks);
* ignores proxy environment variables, caps response size and time.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpcore
import httpx

Resolver = Callable[[str, int], Awaitable[list[str]]]

ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class BlockedUrlError(Exception):
    """The URL may not be fetched. The message is safe to show an admin."""


class ResponseTooLargeError(Exception):
    pass


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def ip_is_public(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped or address.sixtofour
        if mapped is not None:
            address = mapped
    return address.is_global and not address.is_multicast


def check_url(url: str | httpx.URL) -> httpx.URL:
    """Validate the URL's shape (not its addresses); returns it parsed."""
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError, ValueError):
        raise BlockedUrlError("the URL is not valid") from None
    if parsed.scheme not in ("http", "https"):
        raise BlockedUrlError("only http and https URLs can be fetched")
    if not parsed.host:
        raise BlockedUrlError("the URL has no host")
    if parsed.userinfo:
        raise BlockedUrlError("URLs with credentials are not allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise BlockedUrlError(f"port {port} is not allowed")
    return parsed


async def vetted_addresses(host: str, port: int, resolver: Resolver) -> list[str]:
    """The host's addresses, if all are public; else :class:`BlockedUrlError`."""
    try:
        addresses = await resolver(host, port)
    except (OSError, UnicodeError):
        raise BlockedUrlError(f"{host} could not be resolved") from None
    if not addresses:
        raise BlockedUrlError(f"{host} could not be resolved")
    if not all(ip_is_public(ip) for ip in addresses):
        raise BlockedUrlError(f"{host} is not a public internet address")
    return addresses


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connects only to vetted public addresses (see the module docstring)."""

    def __init__(
        self,
        resolver: Resolver = system_resolver,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._resolver = resolver
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await vetted_addresses(host, port, self._resolver)
        except BlockedUrlError as exc:
            raise httpcore.ConnectError(str(exc)) from None
        return await self._inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def guarded_client(
    resolver: Resolver = system_resolver,
    *,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    max_connections: int = 8,
) -> httpx.AsyncClient:
    """An HTTP client for untrusted URLs: no env proxies, guarded connects."""
    transport = httpx.AsyncHTTPTransport(
        trust_env=False,
        limits=httpx.Limits(max_connections=max_connections),
    )
    # httpx has no public hook for httpcore's network backend; the pool
    # reads this attribute when it opens a connection.
    transport._pool._network_backend = GuardedNetworkBackend(resolver)
    return httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        timeout=timeout,
        follow_redirects=False,
    )


@dataclass(frozen=True, slots=True)
class Fetched:
    url: httpx.URL  # after redirects
    status_code: int
    content: bytes
    content_type: str


@dataclass(frozen=True)
class GuardedFetcher:
    """GETs untrusted URLs with the checks above. ``http`` should come from
    :func:`guarded_client`; ``resolver`` vets each hop before connecting."""

    http: httpx.AsyncClient
    user_agent: str
    resolver: Resolver = system_resolver
    headers: Mapping[str, str] = field(default_factory=dict)

    async def get(self, url: str | httpx.URL, *, max_bytes: int) -> Fetched:
        """Raises :class:`BlockedUrlError`, :class:`ResponseTooLargeError` or
        ``httpx.HTTPError``. Non-2xx answers are returned, not raised."""
        current = check_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            port = current.port or (443 if current.scheme == "https" else 80)
            await vetted_addresses(current.host, port, self.resolver)
            request = self.http.build_request(
                "GET",
                current,
                headers={"User-Agent": self.user_agent, **self.headers},
            )
            response = await self.http.send(request, stream=True)
            try:
                location = response.headers.get("location")
                if response.is_redirect and location:
                    current = check_url(current.join(location))
                    continue
                content = await _read_capped(response, max_bytes)
                return Fetched(
                    url=current,
                    status_code=response.status_code,
                    content=content,
                    content_type=response.headers.get("content-type", ""),
                )
            finally:
                await response.aclose()
        raise BlockedUrlError("too many redirects")


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLargeError()
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise ResponseTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)

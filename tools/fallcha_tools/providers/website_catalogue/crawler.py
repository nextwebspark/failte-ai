"""Polite crawl of a shop's product pages (generalised from ``ingest.py``).

* robots.txt is read first. 404/410 (or other 4xx except 401/403) means no
  rules; 401/403 means everything is disallowed; 5xx or no answer stops the
  sync (RFC 9309: assume complete disallow). Disallowed pages are skipped,
  and a ``Crawl-delay`` for this crawler (or ``*``), if longer than the
  configured delay, is honoured (capped at 60 s).
* Sitemaps come from the config, else robots.txt ``Sitemap:`` lines, else
  ``/sitemap.xml``. Sitemap indexes are followed (product sitemaps first),
  gzip sitemaps are inflated, ``<loc>`` values are read with a regex (no XML
  parser, so no entity expansion), and only pages on the site's own host
  (``www.`` or not) are kept, filtered by ``include_paths``.
* Pages are fetched with at most ``max_concurrency`` requests in flight and
  at least ``request_delay_seconds`` between request starts, identifying
  the crawler with an honest User-Agent; at most ``max_products`` pages.
* Every fetch goes through :class:`~fallcha_tools.core.netguard.GuardedFetcher`
  (SSRF checks, redirect checks, size caps).
"""

from __future__ import annotations

import asyncio
import gzip
import html
import re
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from loguru import logger

from fallcha_tools.core.netguard import (
    BlockedUrlError,
    Fetched,
    GuardedFetcher,
    ResponseTooLargeError,
)
from fallcha_tools.core.provider import SyncFailed
from fallcha_tools.providers.website_catalogue.parse import (
    ParsedProduct,
    parse_product,
)
from fallcha_tools.providers.website_catalogue.settings import CatalogueConfig

USER_AGENT_TOKEN = "FallchaCatalogueBot"
USER_AGENT = (
    f"{USER_AGENT_TOKEN}/1.0 (voice agent product catalogue; respects robots.txt)"
)
MAX_ROBOTS_BYTES = 512 * 1024
MAX_SITEMAP_BYTES = 20 * 1024 * 1024
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_SITEMAPS = 50
MAX_CRAWL_DELAY = 60.0
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_PRODUCT_HINT = re.compile(r"product", re.IGNORECASE)

OnProduct = Callable[[ParsedProduct], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    page_urls: tuple[str, ...]  # every product-page URL the sitemaps listed
    complete: bool  # all sitemaps read, and no max_products cut-off
    indexed: int
    skipped: int  # pages without Product JSON-LD, or disallowed
    failed: int


@dataclass(slots=True)
class _Pacer:
    """At least ``interval`` seconds between request starts."""

    interval: float
    _next: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            delay = self._next - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next = loop.time() + self.interval


def _host_key(host: str) -> str:
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _inflate(content: bytes) -> bytes:
    if content[:2] != b"\x1f\x8b":
        return content
    # Bounded: a gzip bomb stops at MAX_SITEMAP_BYTES.
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        data = inflater.decompress(content, MAX_SITEMAP_BYTES + 1)
    except (zlib.error, gzip.BadGzipFile):
        raise ResponseTooLargeError() from None
    if len(data) > MAX_SITEMAP_BYTES:
        raise ResponseTooLargeError()
    return data


def sitemap_locs(content: bytes) -> tuple[bool, list[str]]:
    """(is a sitemap index, the ``<loc>`` URLs)."""
    body = _inflate(content).decode("utf-8", errors="replace")
    is_index = "<sitemapindex" in body[:4096].lower()
    return is_index, [html.unescape(loc) for loc in _LOC.findall(body)]


class CatalogueCrawler:
    def __init__(self, fetcher: GuardedFetcher, config: CatalogueConfig) -> None:
        self._fetcher = fetcher
        self._config = config
        self._site = urlsplit(config.site_url)
        self._origin = f"{self._site.scheme}://{self._site.netloc}"
        self._robots = RobotFileParser()

    # -- public ----------------------------------------------------------------

    async def check(self) -> str:
        """Cheap reachability check for the connection test."""
        await self._load_robots()
        sources = self._sitemap_sources()
        fetched = await self._get(sources[0], MAX_SITEMAP_BYTES)
        if fetched.status_code != 200:
            raise SyncFailed(
                f"the sitemap {sources[0]} answered HTTP {fetched.status_code}"
            )
        _, locs = sitemap_locs(fetched.content)
        if not locs:
            raise SyncFailed(f"the sitemap {sources[0]} lists no pages")
        return f"Found the sitemap {sources[0]} ({len(locs)} entries)"

    async def crawl(self, on_product: OnProduct) -> CrawlOutcome:
        delay = await self._load_robots()
        urls, complete = await self._product_urls()
        if not urls:
            raise SyncFailed("the sitemap lists no pages to import")
        pacer = _Pacer(interval=delay)
        gate = asyncio.Semaphore(self._config.max_concurrency)
        counts = {"indexed": 0, "skipped": 0, "failed": 0}

        async def one(url: str) -> None:
            if not self._robots.can_fetch(USER_AGENT_TOKEN, url):
                counts["skipped"] += 1
                return
            async with gate:
                await pacer.wait()
                try:
                    page = await self._fetcher.get(url, max_bytes=MAX_PAGE_BYTES)
                except (httpx.HTTPError, BlockedUrlError, ResponseTooLargeError):
                    # One flaky page must not stop the run.
                    counts["failed"] += 1
                    return
            if page.status_code != 200:
                counts["failed"] += 1
                return
            product = parse_product(
                page.content.decode("utf-8", errors="replace"),
                url,
                self._config.currency,
            )
            if product is None:
                counts["skipped"] += 1
                return
            await on_product(product)
            counts["indexed"] += 1

        await asyncio.gather(*(one(url) for url in urls))
        return CrawlOutcome(
            page_urls=tuple(urls),
            complete=complete,
            indexed=counts["indexed"],
            skipped=counts["skipped"],
            failed=counts["failed"],
        )

    # -- robots.txt -------------------------------------------------------------

    async def _load_robots(self) -> float:
        """Reads robots.txt; returns the delay between requests to use."""
        url = f"{self._origin}/robots.txt"
        try:
            fetched = await self._fetcher.get(url, max_bytes=MAX_ROBOTS_BYTES)
        except BlockedUrlError as exc:
            raise SyncFailed(f"the site cannot be fetched: {exc}") from None
        except (httpx.HTTPError, ResponseTooLargeError):
            raise SyncFailed("robots.txt could not be read; try again later") from None
        status = fetched.status_code
        if status in (401, 403):
            self._robots.parse(["User-agent: *", "Disallow: /"])
        elif 400 <= status < 500:
            self._robots.parse([])
        elif status >= 300:
            raise SyncFailed(f"robots.txt answered HTTP {status}; try again later")
        else:
            lines = fetched.content.decode("utf-8", errors="replace").splitlines()
            self._robots.parse(lines)
        crawl_delay = self._robots.crawl_delay(USER_AGENT_TOKEN)
        delay = self._config.request_delay_seconds
        if crawl_delay is not None:
            delay = max(delay, min(float(crawl_delay), MAX_CRAWL_DELAY))
        return delay

    def _sitemap_sources(self) -> list[str]:
        if self._config.sitemap_url:
            return [self._config.sitemap_url]
        listed = self._robots.site_maps() or []
        return list(dict.fromkeys(listed)) or [f"{self._origin}/sitemap.xml"]

    # -- sitemaps ---------------------------------------------------------------

    def _wanted(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        if _host_key(parts.hostname) != _host_key(self._site.hostname or ""):
            return False
        patterns = self._config.include_paths
        if not patterns:
            return True
        path = parts.path or "/"
        return any(
            fnmatchcase(path, p) if "*" in p else path.startswith(p) for p in patterns
        )

    async def _product_urls(self) -> tuple[list[str], bool]:
        limit = self._config.max_products
        queue = self._sitemap_sources()
        seen_sitemaps: set[str] = set()
        urls: dict[str, None] = {}
        complete = True
        while queue:
            if len(seen_sitemaps) >= MAX_SITEMAPS:
                complete = False
                break
            sitemap = queue.pop(0)
            if sitemap in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap)
            try:
                fetched = await self._get(sitemap, MAX_SITEMAP_BYTES)
                is_index, locs = sitemap_locs(fetched.content)
            except SyncFailed:
                if not urls and not queue:
                    raise
                complete = False
                continue
            except ResponseTooLargeError:
                complete = False
                continue
            if fetched.status_code != 200:
                if not urls and not queue and len(seen_sitemaps) == 1:
                    raise SyncFailed(
                        f"the sitemap {sitemap} answered HTTP {fetched.status_code}"
                    )
                complete = False
                continue
            if is_index:
                # Product sitemaps first, so a max_products cut keeps products.
                children = sorted(locs, key=lambda u: not _PRODUCT_HINT.search(u))
                queue.extend(children)
                continue
            for loc in locs:
                if self._wanted(loc):
                    urls.setdefault(loc, None)
                    if len(urls) >= limit:
                        return list(urls), False
        return list(urls), complete

    async def _get(self, url: str, max_bytes: int) -> Fetched:
        try:
            return await self._fetcher.get(url, max_bytes=max_bytes)
        except BlockedUrlError as exc:
            raise SyncFailed(f"{url} cannot be fetched: {exc}") from None
        except httpx.HTTPError as exc:
            logger.info("sitemap fetch failed: {}", type(exc).__name__)
            raise SyncFailed(f"{url} could not be loaded") from None

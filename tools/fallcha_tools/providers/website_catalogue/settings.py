"""Per-connection settings of the website catalogue provider."""

from __future__ import annotations

import ipaddress
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_TRANSFER_OFFER = "I can also put you through to one of the team."

PathPattern = Annotated[str, Field(min_length=1, max_length=200)]


def host_key(host: str) -> str:
    """A host compared with and without ``www.``."""
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _public_http_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must be an http(s) URL")
    if parts.username or parts.password:
        raise ValueError("must not contain credentials")
    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None or "." not in host or host.endswith(".local"):
        # Fetches re-check every resolved address; this only catches the
        # obvious cases early, with a clear message.
        raise ValueError("must use the site's public domain name")
    return value


class CatalogueConfig(BaseModel):
    """Which site to import, how politely, and how answers are phrased."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    site_url: str = Field(
        max_length=500,
        description="The shop's home page, e.g. https://www.example.com.",
    )
    sitemap_url: str | None = Field(
        default=None,
        max_length=1000,
        description="Sitemap (or sitemap index) listing product pages. Unset: "
        "the sitemaps named in robots.txt, else /sitemap.xml.",
    )
    currency: str = Field(
        default="EUR",
        pattern=r"^[A-Z]{3}$",
        description="Currency used when a product page does not state one.",
    )
    include_paths: list[PathPattern] | None = Field(
        default=None,
        max_length=20,
        description="Only import pages whose path starts with one of these "
        "(or matches it, with * wildcards), e.g. /products/.",
    )
    max_products: int = Field(
        default=2000,
        ge=1,
        le=20000,
        description="Most product pages fetched per sync.",
    )
    request_delay_seconds: float = Field(
        default=1.0,
        ge=0.2,
        le=30.0,
        description="Pause between page requests (a robots.txt Crawl-delay "
        "for this crawler, if longer, wins).",
    )
    max_concurrency: int = Field(
        default=2, ge=1, le=4, description="Parallel page requests."
    )
    max_sync_minutes: int = Field(
        default=30,
        ge=1,
        le=360,
        description="A sync still running after this long is stopped.",
    )
    max_results: int = Field(
        default=3, ge=1, le=5, description="Products named per search answer."
    )
    no_match_transfer_offer: str = Field(
        default=DEFAULT_TRANSFER_OFFER,
        max_length=300,
        description="Said after 'I could not find that one...'. Empty to "
        "offer no transfer.",
    )

    @field_validator("site_url", "sitemap_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return None if value is None else _public_http_url(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("include_paths")
    @classmethod
    def _paths(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [p.strip() for p in value if p.strip()]
        for path in cleaned:
            if not path.startswith("/"):
                raise ValueError("paths must start with /")
        return cleaned or None

    @model_validator(mode="after")
    def _sitemap_on_site(self) -> Self:
        if self.sitemap_url is None:
            return self
        site = urlsplit(self.site_url).hostname or ""
        sitemap = urlsplit(self.sitemap_url).hostname or ""
        if host_key(site) != host_key(sitemap):
            raise ValueError("sitemap_url must be on the same site as site_url")
        return self

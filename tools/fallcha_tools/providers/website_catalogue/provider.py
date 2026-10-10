"""The website catalogue provider: any shop whose product pages publish
schema.org Product JSON-LD and are listed in a sitemap."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue, ValidationError

from fallcha_tools.core.db import Database
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.netguard import (
    GuardedFetcher,
    Resolver,
    guarded_client,
    system_resolver,
)
from fallcha_tools.core.provider import (
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    OAuthSpec,
    RestContextDependency,
    SyncFailed,
    SyncProgress,
    SyncResult,
)
from fallcha_tools.providers.website_catalogue.crawler import (
    PAGE_TIMEOUT,
    SITEMAP_TIMEOUT,
    USER_AGENT,
    CatalogueCrawler,
)
from fallcha_tools.providers.website_catalogue.parse import ParsedProduct
from fallcha_tools.providers.website_catalogue.rest import build_rest_router
from fallcha_tools.providers.website_catalogue.service import CatalogueService
from fallcha_tools.providers.website_catalogue.settings import CatalogueConfig
from fallcha_tools.providers.website_catalogue.store import (
    UPSERT_BATCH,
    CatalogueStore,
)
from fallcha_tools.providers.website_catalogue.tools import (
    CatalogueToolError,
    register_catalogue_tools,
)

SECONDS_PER_MINUTE = 60.0  # tests shrink it


def _now() -> datetime:
    return datetime.now(UTC)


def _config(ctx: ConnectionContext) -> CatalogueConfig:
    try:
        return CatalogueConfig.model_validate(dict(ctx.config))
    except ValidationError:
        raise CatalogueToolError(
            "the catalogue settings for this connection are missing or invalid"
        ) from None


def _db(ctx: ConnectionContext) -> Database:
    if ctx.db is None:
        raise CatalogueToolError("the catalogue is not available")
    return ctx.db


@dataclass(frozen=True)
class WebsiteCatalogueProvider:
    """Search a shop's products (name, price, stock) imported from its site.

    ``resolver`` resolves host names for the SSRF guard (tests inject one).
    """

    resolver: Resolver = system_resolver
    clock: Any = field(default=_now)
    page_timeout: float = PAGE_TIMEOUT
    sitemap_timeout: float = SITEMAP_TIMEOUT

    @property
    def id(self) -> str:
        return "website-catalogue"

    @property
    def title(self) -> str:
        return "Website product catalogue"

    @property
    def description(self) -> str:
        return (
            "Import a shop's products from its website (pages with schema.org "
            "product data, listed in its sitemap) so agents can answer "
            "questions about products, prices and stock."
        )

    @property
    def icon(self) -> str:
        return "products"

    @property
    def share_hint(self) -> str | None:
        return None

    @property
    def auth_family(self) -> str | None:
        return None

    @property
    def auth_modes(self) -> frozenset[AuthMode]:
        return frozenset({AuthMode.NONE})

    @property
    def scopes(self) -> tuple[str, ...]:
        return ()

    @property
    def config_model(self) -> type[BaseModel]:
        return CatalogueConfig

    @property
    def oauth(self) -> OAuthSpec | None:
        return None

    @property
    def sync_item_label(self) -> str:
        return "products"

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        del auth_mode, secret  # public data: there is no secret

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        register_catalogue_tools(mcp, ctx_factory, self.service_for)

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter:
        return build_rest_router(ctx_dependency, self.service_for)

    def service_for(self, ctx: ConnectionContext) -> CatalogueService:
        return CatalogueService(
            store=CatalogueStore(_db(ctx)),
            config=_config(ctx),
            org_id=ctx.org_id,
            connection_id=ctx.connection_id,
        )

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        try:
            config = _config(ctx)
        except CatalogueToolError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        async with guarded_client(self.resolver) as http:
            crawler = CatalogueCrawler(
                self._fetcher(http),
                config,
                page_timeout=self.page_timeout,
                sitemap_timeout=self.sitemap_timeout,
            )
            try:
                message = await crawler.check()
            except SyncFailed as exc:
                return ConnectionTestResult(ok=False, message=str(exc))
        count = await CatalogueStore(_db(ctx)).count(ctx.org_id, ctx.connection_id)
        return ConnectionTestResult(
            ok=True,
            message=f"{message}; {count} products imported so far",
        )

    async def run_sync(
        self, ctx: ConnectionContext, progress: SyncProgress
    ) -> SyncResult:
        try:
            config = _config(ctx)
            store = CatalogueStore(_db(ctx))
        except CatalogueToolError as exc:
            raise SyncFailed(str(exc)) from None
        limit = config.max_sync_minutes
        try:
            async with asyncio.timeout(limit * SECONDS_PER_MINUTE):
                return await self._sync(ctx, config, store, progress)
        except TimeoutError:
            raise SyncFailed(
                f"the sync took longer than {limit} minutes and was stopped"
            ) from None

    async def _sync(
        self,
        ctx: ConnectionContext,
        config: CatalogueConfig,
        store: CatalogueStore,
        progress: SyncProgress,
    ) -> SyncResult:
        started = self.clock()
        batch: list[ParsedProduct] = []
        indexed = 0

        async def flush() -> None:
            nonlocal batch
            if batch:
                pending, batch = batch, []
                await store.upsert(ctx.org_id, ctx.connection_id, pending, self.clock())

        async def on_product(product: ParsedProduct) -> None:
            nonlocal indexed
            batch.append(product)
            indexed += 1
            if len(batch) >= UPSERT_BATCH:
                await flush()

        async def on_progress(done: int) -> None:
            # Every page and sitemap counts, so a long run that finds few
            # products is never mistaken for a dead one.
            await progress.heartbeat(indexed)
            del done

        async with guarded_client(
            self.resolver, max_connections=config.max_concurrency
        ) as http:
            crawler = CatalogueCrawler(
                self._fetcher(http),
                config,
                on_progress=on_progress,
                page_timeout=self.page_timeout,
                sitemap_timeout=self.sitemap_timeout,
            )
            outcome = await crawler.crawl(on_product)
        await flush()
        if outcome.indexed == 0:
            raise SyncFailed(
                f"no product data (schema.org Product JSON-LD) was found on "
                f"{len(outcome.page_urls)} page(s) "
                f"({outcome.failed} could not be loaded)"
            )
        # The catalogue is what this sync's sitemaps listed (capped at
        # max_products); pages that failed to load keep their old row.
        await store.prune(
            ctx.org_id,
            ctx.connection_id,
            older_than=started,
            keep_urls=outcome.page_urls,
        )
        total = await store.count(ctx.org_id, ctx.connection_id)
        notes = []
        if not outcome.complete:
            notes.append(f"stopped at {config.max_products} pages")
        if outcome.failed:
            notes.append(f"{outcome.failed} page(s) could not be loaded")
        return SyncResult(item_count=total, note="; ".join(notes) or None)

    def _fetcher(self, http: Any) -> GuardedFetcher:
        return GuardedFetcher(http=http, user_agent=USER_AGENT, resolver=self.resolver)

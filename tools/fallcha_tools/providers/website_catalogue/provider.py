"""The website catalogue provider: any shop whose product pages publish
schema.org Product JSON-LD and are listed in a sitemap."""

from __future__ import annotations

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
            crawler = CatalogueCrawler(self._fetcher(http), config)
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
        started = self.clock()
        batch: list[ParsedProduct] = []
        indexed = 0

        async def flush() -> None:
            nonlocal batch
            if batch:
                await store.upsert(ctx.org_id, ctx.connection_id, batch, self.clock())
                batch = []

        async def on_product(product: ParsedProduct) -> None:
            nonlocal indexed
            batch.append(product)
            indexed += 1
            if len(batch) >= UPSERT_BATCH:
                await flush()
            await progress.heartbeat(indexed)

        async with guarded_client(
            self.resolver, max_connections=config.max_concurrency
        ) as http:
            outcome = await CatalogueCrawler(self._fetcher(http), config).crawl(
                on_product
            )
        await flush()
        if outcome.indexed == 0:
            raise SyncFailed(
                f"no product data (schema.org Product JSON-LD) was found on "
                f"{len(outcome.page_urls)} page(s) "
                f"({outcome.failed} could not be loaded)"
            )
        if outcome.complete:
            await store.prune(
                ctx.org_id,
                ctx.connection_id,
                older_than=started,
                keep_urls=outcome.page_urls,
            )
        total = await store.count(ctx.org_id, ctx.connection_id)
        note = None
        if not outcome.complete:
            note = f"stopped at {config.max_products} pages"
        return SyncResult(item_count=total, note=note)

    def _fetcher(self, http: Any) -> GuardedFetcher:
        return GuardedFetcher(http=http, user_agent=USER_AGENT, resolver=self.resolver)

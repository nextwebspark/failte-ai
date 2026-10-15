"""MCP tools, mirroring the original product service's two functions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fallcha_tools.core.provider import ConnectionContext, ConnectionContextFactory
from fallcha_tools.providers.website_catalogue.schemas import (
    DetailResult,
    MaxResults,
    Query,
    SearchResult,
    Sku,
)
from fallcha_tools.providers.website_catalogue.service import CatalogueService

ServiceFactory = Callable[[ConnectionContext], CatalogueService]

_READ_ONLY: dict[str, Any] = {"readOnlyHint": True, "openWorldHint": False}


class CatalogueToolError(Exception):
    """Raised by the service factory; the message is safe to show."""


def register_catalogue_tools(
    mcp: FastMCP[Any],
    ctx_factory: ConnectionContextFactory,
    service_for: ServiceFactory,
) -> None:
    async def service() -> CatalogueService:
        ctx = await ctx_factory()
        try:
            return service_for(ctx)
        except CatalogueToolError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(
        annotations=_READ_ONLY, title="Find products by what the caller describes"
    )
    async def search_products(
        query: Query, max_results: MaxResults = None
    ) -> SearchResult:
        """Find products in the shop's range from how the caller described them.
        Returns real products with price and stock. Always call this before
        naming any product or price; never answer from memory. Read the "say"
        field to the caller."""
        svc = await service()
        return await svc.search(query, max_results)

    @mcp.tool(annotations=_READ_ONLY, title="Get one product's price and details")
    async def product_detail(sku: Sku) -> DetailResult:
        """Get the fuller description and stock position for one product the
        caller has picked, using the sku from a search_products result. Read
        the "say" field to the caller."""
        svc = await service()
        return await svc.detail(sku)

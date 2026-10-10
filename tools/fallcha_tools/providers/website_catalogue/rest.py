"""REST compatibility routes mirroring the original product service.

``POST /v1/website-catalogue/{product_search,product_detail}`` take its JSON
bodies and return its response shapes, so the existing ``http_api`` tools
only need a new URL and a connection key (Bearer or ``X-API-Key``).
"""

# No ``from __future__ import annotations``: FastAPI must resolve the
# dependency alias defined inside ``build_rest_router`` at runtime.

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from fallcha_tools.core.provider import ConnectionContext, RestContextDependency
from fallcha_tools.providers.website_catalogue.schemas import (
    DetailRequest,
    DetailResult,
    SearchRequest,
    SearchResult,
)
from fallcha_tools.providers.website_catalogue.service import CatalogueService
from fallcha_tools.providers.website_catalogue.tools import (
    CatalogueToolError,
    ServiceFactory,
)


def build_rest_router(
    ctx_dependency: RestContextDependency, service_for: ServiceFactory
) -> APIRouter:
    router = APIRouter(tags=["website-catalogue"])
    Ctx = Annotated[ConnectionContext, Depends(ctx_dependency)]

    def service(ctx: ConnectionContext) -> CatalogueService:
        try:
            return service_for(ctx)
        except CatalogueToolError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    # exclude_unset: a miss is {"found": false, ...} without the hit-only keys,
    # exactly as the original answered.
    @router.post("/product_search", response_model_exclude_unset=True)
    async def product_search(body: SearchRequest, ctx: Ctx) -> SearchResult:
        return await service(ctx).search(body.query, body.max_results)

    @router.post("/product_detail", response_model_exclude_unset=True)
    async def product_detail(body: DetailRequest, ctx: Ctx) -> DetailResult:
        return await service(ctx).detail(body.sku)

    return router

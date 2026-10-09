"""Superuser platform model administration: per-organization access and
placement (restricted models, pinning, Enterprise project or region)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.schemas.platform_models import PlatformCatalogOption, PlatformModelPolicy
from api.services.auth.depends import get_superuser
from api.services.configuration.platform import catalog
from api.services.configuration.platform.catalog_view import options_for
from api.services.configuration.platform.policy import (
    InvalidPlatformPolicyError,
    get_platform_model_policy,
    llm_models_in_use,
    save_platform_model_policy,
)

router = APIRouter(prefix="/superuser/platform-models", tags=["superuser"])

Superuser = Annotated[UserModel, Depends(get_superuser)]


class PlatformModelPolicyResponse(BaseModel):
    organization_id: int
    policy: PlatformModelPolicy
    # Restricted models a superuser can add to policy.extra_models.
    restricted_models: list[PlatformCatalogOption]


async def _require_organization(organization_id: int) -> None:
    if await db_client.get_organization_by_id(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")


def _response(
    organization_id: int, policy: PlatformModelPolicy
) -> PlatformModelPolicyResponse:
    return PlatformModelPolicyResponse(
        organization_id=organization_id,
        policy=policy,
        restricted_models=options_for(catalog.RESTRICTED_LLM_MODELS),
    )


@router.get(
    "/organizations/{organization_id}",
    response_model=PlatformModelPolicyResponse,
    include_in_schema=False,
)
async def get_organization_platform_policy(
    organization_id: int, _user: Superuser
) -> PlatformModelPolicyResponse:
    await _require_organization(organization_id)
    return _response(organization_id, await get_platform_model_policy(organization_id))


@router.put(
    "/organizations/{organization_id}",
    response_model=PlatformModelPolicyResponse,
    include_in_schema=False,
)
async def put_organization_platform_policy(
    organization_id: int, policy: PlatformModelPolicy, _user: Superuser
) -> PlatformModelPolicyResponse:
    """Replace the organization's policy (not a partial update)."""
    await _require_organization(organization_id)
    try:
        previous = await get_platform_model_policy(organization_id)
    except InvalidPlatformPolicyError:
        previous = PlatformModelPolicy()
    removed = set(previous.extra_models) - set(policy.extra_models)
    still_used = sorted(removed & await llm_models_in_use(organization_id))
    if still_used:
        # Grandfathered configurations would keep running a model the policy
        # no longer offers; move them off it first.
        raise HTTPException(
            status_code=422,
            detail=f"Still used by this organization: {', '.join(still_used)}",
        )
    saved = await save_platform_model_policy(organization_id, policy)
    return _response(organization_id, saved)

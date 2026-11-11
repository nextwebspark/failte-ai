"""Runtime feature switches as the app reads them.

``GET /features`` is what the signed-in user's organisation sees. ``GET
/features/public`` needs no sign-in: the UI middleware reads it before it
knows who is signed in, and only learns whether a feature is on for anyone.
Platform admins change the switches under ``/superuser/admin/features``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.db import db_client
from api.db.models import UserModel
from api.schemas.platform_admin import FeatureFlagsResponse
from api.services.auth.depends import get_user
from api.services.platform_admin import features

router = APIRouter(prefix="/features", tags=["features"])


@router.get("", response_model=FeatureFlagsResponse, include_in_schema=False)
async def get_features(
    user: Annotated[UserModel, Depends(get_user)],
) -> FeatureFlagsResponse:
    platform, organization = await db_client.get_feature_flag_values(
        user.selected_organization_id
    )
    return FeatureFlagsResponse(
        features=features.effective_flags(platform, organization)
    )


@router.get("/public", response_model=FeatureFlagsResponse, include_in_schema=False)
async def get_public_features() -> FeatureFlagsResponse:
    platform, _ = await db_client.get_feature_flag_values(None)
    return FeatureFlagsResponse(
        features=features.available_somewhere(
            platform, await db_client.features_enabled_for_some_organization()
        )
    )

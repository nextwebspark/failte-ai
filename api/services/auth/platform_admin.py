"""Platform-admin guard for platform-wide resources (e.g. the skill library).

Platform admins are users with ``is_superuser``; they act on resources that
belong to no organization, so no organization role is involved. Unlike
``get_superuser`` this depends on ``get_user`` through FastAPI, so the
dependency graph (and test overrides of ``get_user``) see it.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from api.db.models import UserModel
from api.services.auth.depends import get_user


async def require_platform_admin(
    user: Annotated[UserModel, Depends(get_user)],
) -> UserModel:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin privileges required",
        )
    return user

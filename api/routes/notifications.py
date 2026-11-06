"""Settings > Notifications: who hears about calls."""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.schemas.call_notifications import (
    CallNotificationSettings,
    CallNotificationSettingsResponse,
)
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.call_notifications.settings import (
    load_notification_settings,
    member_recipients,
    save_notification_settings,
)
from api.services.email import get_email_sender
from api.services.sms import get_sms_sender

router = APIRouter(prefix="/organizations", tags=["notifications"])

NotificationsManager = Annotated[
    OrgMembership, Depends(require_permission(Permission.NOTIFICATIONS_MANAGE))
]


def _delivers(factory) -> bool:
    try:
        return factory().delivers
    except Exception:  # noqa: BLE001 - a misconfigured provider sends nothing
        return False


async def _response(
    organization_id: int, settings: CallNotificationSettings
) -> CallNotificationSettingsResponse:
    return CallNotificationSettingsResponse(
        **settings.model_dump(),
        member_recipients=await member_recipients(organization_id),
        email_available=_delivers(get_email_sender),
        sms_available=_delivers(get_sms_sender),
    )


@router.get("/notifications", response_model=CallNotificationSettingsResponse)
async def get_notification_settings(
    membership: NotificationsManager,
) -> CallNotificationSettingsResponse:
    settings = await load_notification_settings(membership.organization_id)
    return await _response(membership.organization_id, settings)


@router.put("/notifications", response_model=CallNotificationSettingsResponse)
async def update_notification_settings(
    request: CallNotificationSettings,
    membership: NotificationsManager,
) -> CallNotificationSettingsResponse:
    settings = await save_notification_settings(membership.organization_id, request)
    return await _response(membership.organization_id, settings)

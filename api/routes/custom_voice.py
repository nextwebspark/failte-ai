"""An owner asks LightMove to set up a voice they already cloned elsewhere."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user, requires
from api.services.auth.permissions import Permission
from api.services.custom_voice import (
    ConsentRequiredError,
    CustomVoiceRequest,
    CustomVoiceRequestIn,
    latest_request,
    submit_request,
)

router = APIRouter(tags=["custom-voice"])


class CustomVoiceStatus(BaseModel):
    request: CustomVoiceRequest | None = None


async def _workflow(workflow_id: int, organization_id: int):
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return workflow


@router.get(
    "/workflow/{workflow_id}/custom-voice",
    response_model=CustomVoiceStatus,
    dependencies=requires(Permission.AGENTS_READ),
)
async def get_custom_voice(workflow_id: int, user: UserModel = Depends(get_user)):
    """The latest custom-voice request for this agent, if any."""
    organization_id = user.selected_organization_id
    await _workflow(workflow_id, organization_id)
    return CustomVoiceStatus(request=await latest_request(organization_id, workflow_id))


@router.post(
    "/workflow/{workflow_id}/custom-voice",
    response_model=CustomVoiceStatus,
    dependencies=requires(Permission.AGENTS_WRITE),
)
async def request_custom_voice(
    workflow_id: int,
    body: CustomVoiceRequestIn,
    user: UserModel = Depends(get_user),
):
    """Ask LightMove to set up a voice the owner already cloned elsewhere. The
    team sets it up by hand; no provider key is asked for or accepted."""
    organization_id = user.selected_organization_id
    workflow = await _workflow(workflow_id, organization_id)
    organization = await db_client.get_organization_by_id(organization_id)
    try:
        request = await submit_request(
            organization_id=organization_id,
            organization_name=getattr(organization, "name", None),
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            requested_by=user.email,
            body=body,
        )
    except ConsentRequiredError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return CustomVoiceStatus(request=request)

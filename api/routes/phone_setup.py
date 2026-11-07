"""How callers reach an agent: its numbers, the owner's setup choice, and
LightMove-provided numbers."""

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api.db import db_client
from api.db.models import UserModel
from api.schemas.phone_setup import (
    AgentPhoneNumber,
    AvailablePlatformNumber,
    AvailablePlatformNumbersResponse,
    NumberKind,
    PhoneSetupCheck,
    PhoneSetupChoice,
    PhoneSetupResponse,
    PhoneSetupUpdateRequest,
    PlatformNumberPurchaseRequest,
)
from api.services.auth.depends import get_user, requires
from api.services.auth.permissions import Permission
from api.services.telephony.inbound_routing import InboundRoutingConflictError
from api.services.telephony.phone_setup import (
    find_first_call,
    read_setup,
    with_setup,
)
from api.services.telephony.platform_numbers import (
    PlatformNumberProviderError,
    PlatformNumbersNotConfiguredError,
    get_platform_number_provider,
    is_platform_number,
    platform_numbers_country,
)
from api.services.telephony.platform_numbers.service import (
    buy_platform_number,
    search_platform_numbers,
)

router = APIRouter(tags=["phone-setup"])


def _organization_id(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


async def _ensure_workflow(workflow_id: int, organization_id: int) -> None:
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Agent not found")


async def _setup_response(workflow_id: int, organization_id: int) -> PhoneSetupResponse:
    rows = await db_client.list_phone_numbers_for_workflow(workflow_id, organization_id)
    numbers = []
    for row, config_name, provider, provider_inactive in rows:
        setup = read_setup(row.extra_metadata)
        choice = None
        check = PhoneSetupCheck(status="not_started")
        if setup and setup.get("method") and setup.get("started_at"):
            try:
                choice = PhoneSetupChoice.model_validate(setup)
            except ValueError:
                choice = None
        if choice is not None:
            first = await find_first_call(
                workflow_id=workflow_id,
                organization_id=organization_id,
                number=row,
                db=db_client,
            )
            check = (
                PhoneSetupCheck(
                    status="received",
                    first_call_at=first.at,
                    first_call_run_id=first.run_id,
                    forwarded_from=first.forwarded_from,
                )
                if first
                else PhoneSetupCheck(status="waiting")
            )
        numbers.append(
            AgentPhoneNumber(
                id=row.id,
                telephony_configuration_id=row.telephony_configuration_id,
                address=row.address,
                address_normalized=row.address_normalized,
                label=row.label,
                provider=provider,
                provider_name=config_name,
                is_active=row.is_active,
                provider_inactive=provider_inactive,
                lightmove_number=is_platform_number(row.extra_metadata),
                setup=choice,
                check=check,
            )
        )
    return PhoneSetupResponse(
        platform_numbers_available=get_platform_number_provider() is not None,
        numbers=numbers,
    )


@router.get(
    "/workflow/{workflow_id}/phone-setup",
    response_model=PhoneSetupResponse,
    dependencies=requires(Permission.TELEPHONY_READ),
)
async def get_phone_setup(workflow_id: int, user: UserModel = Depends(get_user)):
    """The numbers that ring this agent, how each is set up, and whether a call
    has come through since."""
    organization_id = _organization_id(user)
    await _ensure_workflow(workflow_id, organization_id)
    return await _setup_response(workflow_id, organization_id)


@router.put(
    "/workflow/{workflow_id}/phone-setup",
    response_model=PhoneSetupResponse,
    dependencies=requires(Permission.TELEPHONY_WRITE),
)
async def update_phone_setup(
    workflow_id: int,
    request: PhoneSetupUpdateRequest,
    user: UserModel = Depends(get_user),
):
    """Save how callers reach this agent through one of its numbers."""
    organization_id = _organization_id(user)
    await _ensure_workflow(workflow_id, organization_id)
    number = await db_client.get_phone_number_for_org(
        request.phone_number_id, organization_id
    )
    if not number or number.inbound_workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Phone number not found")
    if request.method != "new_number" and request.forward_when is None:
        raise HTTPException(
            status_code=400, detail="Choose when calls should go to your agent."
        )

    await db_client.update_phone_number(
        phone_number_id=number.id,
        telephony_configuration_id=number.telephony_configuration_id,
        extra_metadata=with_setup(
            number.extra_metadata,
            method=request.method,
            forward_when=request.forward_when,
        ),
    )
    return await _setup_response(workflow_id, organization_id)


@router.get(
    "/platform-numbers/available",
    response_model=AvailablePlatformNumbersResponse,
    dependencies=requires(Permission.TELEPHONY_WRITE),
)
async def list_available_platform_numbers(
    kind: NumberKind = Query("local"),
    user: UserModel = Depends(get_user),
):
    """Numbers LightMove can get for an agent right now. 503 when LightMove
    numbers are not switched on for this deployment."""
    _organization_id(user)
    try:
        found = await search_platform_numbers(kind)
    except PlatformNumbersNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except PlatformNumberProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return AvailablePlatformNumbersResponse(
        country=platform_numbers_country(),
        numbers=[
            AvailablePlatformNumber(
                phone_number=n.phone_number,
                friendly_name=n.friendly_name,
                kind=n.kind,
                locality=n.locality,
                region=n.region,
            )
            for n in found
        ],
    )


@router.post(
    "/workflow/{workflow_id}/platform-number",
    response_model=PhoneSetupResponse,
    dependencies=requires(Permission.TELEPHONY_WRITE),
)
async def get_platform_number(
    workflow_id: int,
    request: PlatformNumberPurchaseRequest,
    user: UserModel = Depends(get_user),
):
    """Get a LightMove-provided number and point it at this agent.

    No charge is made: billing for LightMove numbers is not decided yet (see
    ``record_platform_number_for_billing``).
    """
    organization_id = _organization_id(user)
    await _ensure_workflow(workflow_id, organization_id)
    try:
        await buy_platform_number(
            organization_id=organization_id,
            workflow_id=workflow_id,
            phone_number=request.phone_number,
        )
    except PlatformNumbersNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except InboundRoutingConflictError:
        raise HTTPException(
            status_code=409, detail="That number is already in use. Pick another."
        )
    except PlatformNumberProviderError as e:
        logger.warning(
            f"Platform number purchase failed for org {organization_id}: {e.detail}"
        )
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _setup_response(workflow_id, organization_id)

"""Share a call's recording with an expiring link, and the public side of it.

* ``POST /calls/{run_id}/recording-shares``: make a link (24 hours or 7 days).
* ``GET /calls/{run_id}/recording-shares``: the links still working.
* ``DELETE /calls/{run_id}/recording-shares/{share_id}``: turn one off.
* ``GET /public/recording/{token}``: no sign-in; redirects to a short-lived
  signed URL for the recording while the link works.
* ``GET /public/recording/{token}/info``: no sign-in; what the listening page
  shows (business name, call date, expiry). Never the caller's number or name.

Anyone who can read calls can share and revoke.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel, Field

from api.constants import UI_APP_URL
from api.db import db_client
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.calls.recording_shares import (
    DEFAULT_EXPIRY,
    ShareExpiry,
    ShareState,
    active_shares,
    add_share,
    find_share,
    new_share,
    new_token,
    parse_token,
    revoke,
    share_state,
    signed_url_seconds,
    stored_shares,
)
from api.services.storage import get_storage_for_backend

router = APIRouter(tags=["calls"])

CallsReader = Annotated[
    OrgMembership, Depends(require_permission(Permission.CALLS_READ))
]

# Shared pages and redirects: never cached, never leak the link onwards.
_PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class CreateRecordingShareRequest(BaseModel):
    expires_in: ShareExpiry = Field(
        default=DEFAULT_EXPIRY, description="How long the link works: 24h or 7d."
    )


class RecordingShare(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    created_by: Optional[str] = None


class CreatedRecordingShare(RecordingShare):
    url: str = Field(description="The link to send. Shown only once.")


class RecordingShareList(BaseModel):
    shares: list[RecordingShare]


class SharedRecordingInfo(BaseModel):
    status: Literal["active", "expired", "revoked", "unavailable"]
    business_name: Optional[str] = None
    called_at: Optional[datetime] = None
    timezone: Optional[str] = None
    duration_seconds: Optional[int] = None
    expires_at: Optional[datetime] = None


def share_url(token: str) -> str:
    return f"{UI_APP_URL.rstrip('/')}/listen/{token}"


@router.post(
    "/calls/{run_id}/recording-shares",
    response_model=CreatedRecordingShare,
    status_code=201,
    responses={
        404: {"description": "No such call"},
        409: {"description": "No recording"},
    },
)
async def create_recording_share(
    run_id: int,
    membership: CallsReader,
    request: Optional[CreateRecordingShareRequest] = None,
) -> CreatedRecordingShare:
    """Make a link that plays this call's recording without signing in."""
    expiry = (request or CreateRecordingShareRequest()).expires_in
    now = datetime.now(UTC)
    token, token_hash = new_token(run_id)
    share = new_share(
        token_hash=token_hash,
        expiry=expiry,
        user_id=membership.user.id,
        name=membership.user.name,
        email=membership.user.email,
        now=now,
    )
    no_recording = False

    def change(call: dict[str, Any], shares: list[dict[str, Any]]):
        nonlocal no_recording
        if not call.get("recording_url"):
            no_recording = True
            return None
        return add_share(shares, share, now)

    stored = await db_client.change_recording_shares(
        membership.organization_id, run_id, change
    )
    if no_recording:
        raise HTTPException(
            status_code=409, detail="This call has no recording to share."
        )
    if stored is None:
        raise HTTPException(status_code=404, detail="Call not found")
    logger.info(f"Recording share {share['id']} made for run {run_id}")
    return CreatedRecordingShare(
        id=share["id"],
        created_at=share["created_at"],
        expires_at=share["expires_at"],
        created_by=share["created_by"],
        url=share_url(token),
    )


@router.get("/calls/{run_id}/recording-shares", response_model=RecordingShareList)
async def list_recording_shares(
    run_id: int, membership: CallsReader
) -> RecordingShareList:
    """The links to this call's recording that still work."""
    found = await db_client.get_recording_shares(membership.organization_id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Call not found")
    _, shares = found
    return RecordingShareList(
        shares=[RecordingShare(**s) for s in active_shares(shares, datetime.now(UTC))]
    )


@router.delete("/calls/{run_id}/recording-shares/{share_id}", status_code=204)
async def revoke_recording_share(run_id: int, share_id: str, membership: CallsReader):
    """Turn a link off at once."""
    now = datetime.now(UTC)
    stored = await db_client.change_recording_shares(
        membership.organization_id,
        run_id,
        lambda _call, shares: revoke(shares, share_id, now),
    )
    if stored is None:
        raise HTTPException(status_code=404, detail="Link not found")
    logger.info(f"Recording share {share_id} revoked on run {run_id}")
    return Response(status_code=204)


async def _shared_call(token: str):
    """(call, its link) for a token, or (call or None, None) when it doesn't match."""
    parsed = parse_token(token)
    if parsed is None:
        return None, None
    run_id, secret = parsed
    call = await db_client.get_shared_call(run_id)
    if call is None:
        return None, None
    return call, find_share(stored_shares(call["annotations"]), secret)


def _business_name(call: dict[str, Any]) -> str:
    for source in (call.get("initial_context"), call.get("template_context_variables")):
        name = (source or {}).get("business_name") if isinstance(source, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    return (call.get("organization_name") or "").strip() or "Your business"


async def _timezone(organization_id: int) -> str:
    from api.services.organization_preferences import get_organization_preferences

    try:
        zone = (await get_organization_preferences(organization_id)).timezone
        if zone:
            ZoneInfo(zone)
            return zone
    except (ZoneInfoNotFoundError, ValueError):
        pass
    except Exception:  # noqa: BLE001 - the default zone is a fine answer
        pass
    return "Europe/Dublin"


@router.get(
    "/public/recording/{token}/info",
    response_model=SharedRecordingInfo,
    responses={404: {"description": "Not a link we know"}},
)
async def shared_recording_info(token: str, response: Response) -> SharedRecordingInfo:
    """What the public listening page shows. No sign-in."""
    response.headers.update(_PRIVATE_HEADERS)
    call, share = await _shared_call(token)
    if share is None:
        # Also a purged call: retention clears its links with the rest of it.
        # Saying so would tell anyone holding a made-up token that the call
        # existed, so it reads the same as an unknown link.
        raise HTTPException(
            status_code=404, detail="This link isn't valid.", headers=_PRIVATE_HEADERS
        )
    now = datetime.now(UTC)
    state = share_state(share, now)
    if state == ShareState.REVOKED:
        return SharedRecordingInfo(status="revoked")
    if state == ShareState.EXPIRED:
        return SharedRecordingInfo(status="expired", expires_at=share.get("expires_at"))
    if not call.get("recording_url"):
        return SharedRecordingInfo(status="unavailable")
    duration = (call.get("usage_info") or {}).get("call_duration_seconds")
    return SharedRecordingInfo(
        status="active",
        business_name=_business_name(call),
        called_at=call["created_at"],
        timezone=await _timezone(call["organization_id"]),
        duration_seconds=int(round(duration))
        if isinstance(duration, (int, float))
        else None,
        expires_at=share.get("expires_at"),
    )


@router.get(
    "/public/recording/{token}",
    responses={
        302: {"description": "To a short-lived signed URL for the recording"},
        404: {"description": "Not a link we know"},
        410: {
            "description": "The link expired or was turned off, or the recording is gone"
        },
    },
)
async def play_shared_recording(token: str):
    """The recording behind a shared link. No sign-in; checks the link's
    expiry on every request and redirects to a signed URL that lasts an hour
    at most, and never past the link's expiry."""
    call, share = await _shared_call(token)
    if share is None:
        raise HTTPException(
            status_code=404, detail="This link isn't valid.", headers=_PRIVATE_HEADERS
        )
    now = datetime.now(UTC)
    if share_state(share, now) != ShareState.ACTIVE:
        raise HTTPException(
            status_code=410,
            detail="This link no longer works.",
            headers=_PRIVATE_HEADERS,
        )
    if not call.get("recording_url"):
        raise HTTPException(
            status_code=410,
            detail="This recording is no longer available.",
            headers=_PRIVATE_HEADERS,
        )
    try:
        storage = get_storage_for_backend(call.get("storage_backend"))
        signed = await storage.aget_signed_url(
            file_path=call["recording_url"],
            expiration=signed_url_seconds(share, now),
            force_inline=True,
        )
    except Exception as exc:  # noqa: BLE001 - logged; the listener gets a plain 502
        logger.error(
            f"Signed URL for shared recording on run {call['id']} failed: {exc}"
        )
        signed = None
    if not signed:
        raise HTTPException(
            status_code=502,
            detail="We couldn't load the recording.",
            headers=_PRIVATE_HEADERS,
        )
    return RedirectResponse(url=signed, status_code=302, headers=_PRIVATE_HEADERS)

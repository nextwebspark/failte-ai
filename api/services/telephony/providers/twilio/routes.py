"""Twilio telephony routes (webhooks, status callbacks, answer URLs).

Mounted under ``/api/v1/telephony`` by ``api.routes.telephony`` via the
provider registry — see ProviderSpec.router.
"""

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pipecat.utils.run_context import set_current_run_id
from starlette.responses import HTMLResponse, Response

from api.db import db_client
from api.services.telephony.call_transfer_manager import get_call_transfer_manager
from api.services.telephony.factory import get_telephony_provider_for_run
from api.services.telephony.providers.twilio.introduction import (
    caller_left,
    introduction_twiml,
    process_introduction_status,
)
from api.services.telephony.status_processor import (
    StatusCallbackRequest,
    _process_status_update,
)
from api.services.telephony.transfer_audio import get_transfer_audio
from api.services.telephony.transfer_event_protocol import TransferEventType

router = APIRouter()


@router.post("/twiml", include_in_schema=False)
async def handle_twiml_webhook(
    workflow_id: int,
    workflow_run_id: int,
    organization_id: int,
    request: Request,
):
    """
    Handle initial webhook from telephony provider.
    Returns provider-specific response (e.g., TwiML for Twilio).
    """

    workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
    provider = await get_telephony_provider_for_run(workflow_run, organization_id)
    callback_data = dict(await request.form())

    is_valid = await provider.verify_inbound_signature(
        str(request.url),
        callback_data,
        dict(request.headers),
    )
    if not is_valid:
        logger.warning(
            f"[run {workflow_run_id}] Invalid Twilio signature on answer webhook"
        )
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    response_content = await provider.get_webhook_response(
        workflow_id, organization_id, workflow_run_id
    )

    return HTMLResponse(content=response_content, media_type="application/xml")


@router.post("/twilio/status-callback/{workflow_run_id}")
async def handle_twilio_status_callback(
    workflow_run_id: int,
    request: Request,
):
    """Handle Twilio-specific status callbacks."""
    set_current_run_id(workflow_run_id)

    # Parse form data
    form_data = await request.form()
    callback_data = dict(form_data)

    logger.info(
        f"[run {workflow_run_id}] Received status callback: {json.dumps(callback_data)}"
    )

    # Get workflow run to find organization
    workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
    if not workflow_run:
        logger.warning(f"Workflow run {workflow_run_id} not found for status callback")
        return {"status": "ignored", "reason": "workflow_run_not_found"}

    # Get workflow and provider
    workflow = await db_client.get_workflow_by_id(workflow_run.workflow_id)
    if not workflow:
        logger.warning(f"Workflow {workflow_run.workflow_id} not found")
        return {"status": "ignored", "reason": "workflow_not_found"}

    provider = await get_telephony_provider_for_run(
        workflow_run, workflow.organization_id
    )

    is_valid = await provider.verify_inbound_signature(
        str(request.url),
        callback_data,
        dict(request.headers),
    )
    if not is_valid:
        logger.warning(f"Invalid webhook signature for workflow run {workflow_run_id}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if callback_data.get("CallStatus") == "completed":
        manager = await get_call_transfer_manager()
        transfer = await manager.find_transfer_context_for_call(
            callback_data.get("CallSid", "")
        )
        if (
            transfer
            and transfer.workflow_run_id == workflow_run_id
            and transfer.introduction_audio_url
        ):
            await caller_left(manager, transfer, provider)

    # Parse the callback data into generic format
    parsed_data = provider.parse_status_callback(callback_data)

    # Create StatusCallbackRequest from parsed data
    status_update = StatusCallbackRequest(
        call_id=parsed_data["call_id"],
        status=parsed_data["status"],
        from_number=parsed_data.get("from_number"),
        to_number=parsed_data.get("to_number"),
        direction=parsed_data.get("direction"),
        duration=parsed_data.get("duration"),
        extra=parsed_data.get("extra", {}),
    )

    # Process the status update
    await _process_status_update(workflow_run_id, status_update)

    return {"status": "success"}


@router.get("/twilio/transfer-audio/{token}", include_in_schema=False)
async def transfer_audio(token: str):
    # Play requests have no Dograh login. A random 256-bit capability identifies
    # one bounded clip, expires in Redis, and never grants access to other files.
    audio = await get_transfer_audio(token)
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio unavailable")
    return Response(
        audio, media_type="audio/wav", headers={"Cache-Control": "no-store"}
    )


async def _verified_introduction_transfer(transfer_id: str, request: Request):
    manager = await get_call_transfer_manager()
    transfer = await manager.get_transfer_context(transfer_id)
    if not transfer or not transfer.introduction_audio_url:
        raise HTTPException(status_code=404, detail="Transfer unavailable")
    run = await db_client.get_workflow_run_by_id(transfer.workflow_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Transfer unavailable")
    workflow = await db_client.get_workflow_by_id(run.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Transfer unavailable")
    provider = await get_telephony_provider_for_run(run, workflow.organization_id)
    data = dict(await request.form())
    if (
        provider.PROVIDER_NAME != "twilio"
        or not await provider.verify_inbound_signature(
            str(request.url), data, dict(request.headers)
        )
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    # Twilio may request the destination TwiML before Calls.json returns its SID.
    # Its signed AccountSid authenticates that first request. Subsequent requests
    # must belong to one of the two known legs.
    if transfer.call_sid and data.get("CallSid") not in (
        transfer.call_sid,
        transfer.original_call_sid,
    ):
        raise HTTPException(status_code=403, detail="Call does not belong to transfer")
    return manager, transfer, provider, data


@router.post("/twilio/transfer-introduction/{transfer_id}", include_in_schema=False)
async def transfer_introduction(
    transfer_id: str, request: Request, skip_audio: bool = False
):
    manager, transfer, _, _ = await _verified_introduction_transfer(
        transfer_id, request
    )
    result = await manager.get_transfer_result(transfer_id)
    if result and result.type == TransferEventType.TRANSFER_FAILED:
        return Response("<Response><Hangup /></Response>", media_type="application/xml")
    return Response(
        introduction_twiml(
            transfer.conference_name,
            None if skip_audio else transfer.introduction_audio_url,
        ),
        media_type="application/xml",
    )


@router.post("/twilio/transfer-status/{transfer_id}", include_in_schema=False)
async def introduction_transfer_status(transfer_id: str, request: Request):
    manager, transfer, provider, data = await _verified_introduction_transfer(
        transfer_id, request
    )
    if data.get("CallSid") == transfer.original_call_sid:
        raise HTTPException(status_code=403, detail="Expected destination call")
    await process_introduction_status(manager, transfer, provider, data)
    return {"status": "success"}


# ======== LINES BUSY ========
# A caller who rang while every line was busy: forwarded to the team or
# asked for a voicemail (``lines_busy.py``). These callbacks only ever act
# on a run stored as a turned-away call, and only with Twilio's signature.


def _xml(content: str) -> Response:
    return Response(content=content, media_type="application/xml")


async def _verified_turned_away_call(workflow_run_id: int, request: Request):
    from api.services.telephony.lines_busy import get_turned_away_run

    set_current_run_id(workflow_run_id)
    data = dict(await request.form())
    run = await get_turned_away_run(workflow_run_id)
    workflow = (
        await db_client.get_workflow_by_id(run.workflow_id) if run is not None else None
    )
    if run is None or workflow is None:
        raise HTTPException(status_code=404, detail="Call not found")
    provider = await get_telephony_provider_for_run(run, workflow.organization_id)
    if not await provider.verify_inbound_signature(
        str(request.url), data, dict(request.headers)
    ):
        logger.warning(f"[run {workflow_run_id}] Invalid Twilio signature (lines busy)")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if data.get("CallSid") and data.get("CallSid") != (run.gathered_context or {}).get(
        "call_id"
    ):
        raise HTTPException(status_code=403, detail="Call does not belong to run")
    return run, provider, data


@router.post(
    "/twilio/lines-busy/{workflow_run_id}/dial-result", include_in_schema=False
)
async def lines_busy_dial_result(workflow_run_id: int, request: Request):
    """The forward to the team ended: answered, or a voicemail instead."""
    from api.services.calls.lines_busy import forward_record
    from api.services.telephony.lines_busy import note_forward_result, stored_plan
    from api.services.telephony.providers.twilio import lines_busy as twiml
    from api.utils.common import get_backend_endpoints

    run, _, data = await _verified_turned_away_call(workflow_run_id, request)
    status = (data.get("DialCallStatus") or "").lower()
    record = forward_record(status, data.get("DialCallDuration"))
    caller_gone = (data.get("CallStatus") or "").lower() == "completed"
    plan = stored_plan(run)
    take_message = (
        record["result"] != "answered"
        and not caller_gone
        and bool(plan and plan.voicemail_fallback)
    )
    await note_forward_result(workflow_run_id, record, finished=not take_message)
    if record["result"] == "answered" or caller_gone:
        return _xml(twiml.hangup_twiml())
    if not take_message:
        return _xml(twiml.busy_twiml())
    backend_endpoint, _ = await get_backend_endpoints()
    return _xml(
        twiml.voicemail_twiml(backend_endpoint, workflow_run_id, after_forward=True)
    )


@router.post(
    "/twilio/lines-busy/{workflow_run_id}/voicemail-done", include_in_schema=False
)
async def lines_busy_voicemail_done(
    workflow_run_id: int, request: Request, empty: int = 0
):
    """The voicemail ended (or the caller left none): say goodbye. The file
    itself comes to ``recording`` once Twilio has it ready."""
    from api.services.telephony.lines_busy import finish_turned_away_call
    from api.services.telephony.providers.twilio import lines_busy as twiml

    _, _, data = await _verified_turned_away_call(workflow_run_id, request)
    try:
        seconds = int(float(data.get("RecordingDuration") or 0))
    except ValueError:
        seconds = 0
    await finish_turned_away_call(workflow_run_id)
    return _xml(twiml.goodbye_twiml(left_message=not empty and seconds > 0))


@router.post("/twilio/lines-busy/{workflow_run_id}/recording", include_in_schema=False)
async def lines_busy_recording(workflow_run_id: int, request: Request):
    """The voicemail file is ready: keep it as the call's recording."""
    from api.services.telephony.lines_busy import store_voicemail

    _, provider, data = await _verified_turned_away_call(workflow_run_id, request)
    if (data.get("RecordingStatus") or "completed") != "completed":
        return {"status": "ignored"}
    seconds = data.get("RecordingDuration")
    url = data.get("RecordingUrl") or ""
    audio = await provider.download_recording(url) if url else None
    stored = await store_voicemail(workflow_run_id, audio, seconds)
    if stored:
        await provider.delete_recording(data.get("RecordingSid") or "")
    return {"status": "success", "stored": stored}

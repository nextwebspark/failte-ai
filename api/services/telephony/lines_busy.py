"""Answer an inbound call that can't get an agent slot (every line busy).

Called by the inbound routes instead of rejecting the call: it decides what
to do (``api.services.calls.lines_busy.plan_lines_busy``), stores the call
so the owner sees it (Calls, Follow-ups, Reports), and returns the
provider's own instructions: forward with its dial verb, take a voicemail
with its record verb, or say the busy line. No AI runs and no agent slot is
taken. Providers opt in with ``lines_busy_support`` / ``lines_busy_response``
on ``TelephonyProvider``; the rest keep today's busy line, but the call is
still recorded.

Never raises: if anything goes wrong the caller hears today's busy line.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.db import db_client
from api.enums import CallType, WorkflowRunState
from api.errors.telephony_errors import TelephonyError, log_telephony_error
from api.services.calls.lines_busy import (
    DISPOSITION,
    FORWARD_KEY,
    PLAN_KEY,
    VOICEMAIL_KEY,
    LinesBusyAction,
    LinesBusyPlan,
    plan_lines_busy,
)
from api.services.workflow.opening_hours import transfer_closed


def _busy_line(provider_class) -> Any:
    # Instrumented by the registry: logs the CONCURRENT_CALL_LIMIT failure.
    return provider_class.generate_validation_error_response(
        TelephonyError.CONCURRENT_CALL_LIMIT
    )


async def _own_numbers(workflow, organization_id: int, called: str | None) -> list[str]:
    numbers = [called] if called else []
    try:
        numbers += [
            address
            for address, _ in await db_client.list_inbound_numbers_for_workflow(
                workflow.id, organization_id
            )
        ]
    except Exception as e:  # noqa: BLE001 - the called number is still refused
        logger.warning(f"Lines busy: couldn't list the agent's numbers: {e}")
    return numbers


def provider_support(provider_instance) -> frozenset[str]:
    support = getattr(provider_instance, "lines_busy_support", None)
    if not callable(support):
        return frozenset()
    try:
        return frozenset(support())
    except Exception:  # noqa: BLE001
        return frozenset()


async def record_turned_away_call(
    *,
    workflow,
    organization_id: int,
    provider: str,
    normalized_data,
    telephony_configuration_id: int | None,
    phone_number_id: int | None,
    plan: LinesBusyPlan,
    limit: int | None,
    now: datetime | None = None,
) -> int | None:
    """Store a turned-away call as an inbound run that never reached the
    agent. Returns its id, or None if it couldn't be stored."""
    now = now or datetime.now(UTC)
    suffix = int(uuid.uuid4().hex[:8], 16) % 100000000
    try:
        run = await db_client.create_workflow_run(
            f"WR-TEL-BUSY-{suffix:08d}",
            workflow.id,
            provider,
            user_id=workflow.user_id,
            call_type=CallType.INBOUND,
            initial_context={
                "caller_number": normalized_data.from_number,
                "called_number": normalized_data.to_number,
                "direction": "inbound",
                "provider": provider,
                "telephony_configuration_id": telephony_configuration_id,
            },
            gathered_context={
                "call_id": normalized_data.call_id,
                "mapped_call_disposition": DISPOSITION,
                PLAN_KEY: {**plan.as_record(limit), "at": now.isoformat()},
            },
            logs={
                "inbound_webhook": {
                    "account_id": normalized_data.account_id,
                    "from_country": normalized_data.from_country,
                    "to_country": normalized_data.to_country,
                    "from_phone_number_id": phone_number_id,
                    "raw_webhook_data": normalized_data.raw_data,
                },
            },
            organization_id=organization_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Lines busy: couldn't store the turned-away call: {e}")
        return None
    if plan.action == LinesBusyAction.BUSY_MESSAGE:
        # Nothing more will happen on it.
        await finish_turned_away_call(run.id)
    logger.info(
        f"Lines busy: org {organization_id} call {normalized_data.call_id} stored "
        f"as run {run.id}, action={plan.action.value} reason={plan.reason}"
    )
    return run.id


async def record_hung_up_call(
    *,
    workflow,
    organization_id: int,
    provider: str,
    caller_number: str | None,
    called_number: str | None,
    call_id: str,
    telephony_configuration_id: int | None,
    phone_number_id: int | None,
    limit: int | None,
) -> int | None:
    """Keep a turned-away call on a provider that can only end it (no busy
    line, no forward, no voicemail), so the owner still sees it and can ring
    the caller back."""
    from types import SimpleNamespace

    from api.services.calls.lines_busy import HUNG_UP_REASON, stored_choice

    facts = getattr(workflow, "template_context_variables", None) or {}
    return await record_turned_away_call(
        workflow=workflow,
        organization_id=organization_id,
        provider=provider,
        normalized_data=SimpleNamespace(
            from_number=caller_number,
            to_number=called_number,
            call_id=call_id,
            account_id=None,
            from_country=None,
            to_country=None,
            raw_data={},
        ),
        telephony_configuration_id=telephony_configuration_id,
        phone_number_id=phone_number_id,
        plan=LinesBusyPlan(
            LinesBusyAction.BUSY_MESSAGE, stored_choice(facts), reason=HUNG_UP_REASON
        ),
        limit=limit,
    )


async def finish_turned_away_call(
    workflow_run_id: int, gathered: dict[str, Any] | None = None
) -> None:
    """Mark the turned-away call finished, with what the provider told us.
    Never charges it: the run gets no call duration."""
    try:
        await db_client.update_workflow_run(
            run_id=workflow_run_id,
            is_completed=True,
            state=WorkflowRunState.COMPLETED.value,
            gathered_context=gathered or None,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Lines busy: couldn't finish run {workflow_run_id}: {e}")


async def note_forward_result(
    workflow_run_id: int, record: dict[str, Any], *, finished: bool
) -> None:
    gathered = {FORWARD_KEY: record}
    if finished:
        await finish_turned_away_call(workflow_run_id, gathered)
        return
    try:
        await db_client.update_workflow_run(
            run_id=workflow_run_id, gathered_context=gathered
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Lines busy: couldn't store run {workflow_run_id}'s forward: {e}")


async def store_voicemail(
    workflow_run_id: int, audio: bytes | None, seconds: Any
) -> bool:
    """Keep the caller's message as the call's recording (Listen on the
    call and on its follow-up). Returns whether it was stored."""
    from api.services.workflow_run_artifacts import upload_workflow_run_artifacts

    try:
        length = int(float(seconds or 0))
    except (TypeError, ValueError):
        length = 0
    stored = False
    if audio and length > 0:
        await upload_workflow_run_artifacts(workflow_run_id, mixed_audio_wav=audio)
        run = await db_client.get_workflow_run_by_id(workflow_run_id)
        stored = bool(run and run.recording_url)
    try:
        await db_client.update_workflow_run(
            run_id=workflow_run_id,
            gathered_context={
                VOICEMAIL_KEY: {"seconds": length if stored else 0, "stored": stored}
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"Lines busy: couldn't note run {workflow_run_id}'s voicemail: {e}"
        )
    return stored


async def get_turned_away_run(workflow_run_id: int):
    """The run, only when it is a turned-away call (callbacks for anything
    else are refused)."""
    from api.services.calls.lines_busy import is_lines_busy

    run = await db_client.get_workflow_run_by_id(workflow_run_id)
    if run is None or not is_lines_busy(run.gathered_context):
        return None
    return run


def stored_plan(run) -> LinesBusyPlan | None:
    record = (getattr(run, "gathered_context", None) or {}).get(PLAN_KEY) or {}
    try:
        action = LinesBusyAction(record.get("action"))
    except ValueError:
        return None
    chosen = record.get("chosen")
    return LinesBusyPlan(
        action=action,
        chosen=LinesBusyAction(chosen) if chosen in set(LinesBusyAction) else None,
        destination=record.get("forward_to"),
        reason=record.get("reason"),
        voicemail_fallback=bool(record.get("voicemail_fallback")),
    )


async def lines_busy_response(
    *,
    provider_class,
    provider_instance,
    workflow,
    organization_id: int,
    normalized_data,
    telephony_configuration_id: int | None,
    phone_number_id: int | None,
    limit: int | None,
    now: datetime | None = None,
) -> Any:
    """What the provider is told to do with a caller who can't get an agent
    slot. Stores the call either way."""
    from api.utils.common import get_backend_endpoints

    now = now or datetime.now(UTC)
    provider = provider_class.PROVIDER_NAME
    try:
        facts = getattr(workflow, "template_context_variables", None) or {}
        support = provider_support(provider_instance)
        plan = plan_lines_busy(
            facts,
            support=support,
            own_numbers=await _own_numbers(
                workflow, organization_id, normalized_data.to_number
            ),
            closed=transfer_closed(facts, now),
        )
        run_id = await record_turned_away_call(
            workflow=workflow,
            organization_id=organization_id,
            provider=provider,
            normalized_data=normalized_data,
            telephony_configuration_id=telephony_configuration_id,
            phone_number_id=phone_number_id,
            plan=plan,
            limit=limit,
            now=now,
        )
        respond = getattr(provider_instance, "lines_busy_response", None)
        if run_id is None or not support or not callable(respond):
            return _busy_line(provider_class)
        log_telephony_error(TelephonyError.CONCURRENT_CALL_LIMIT, provider=provider)
        try:
            backend_endpoint, _ = await get_backend_endpoints()
            return await respond(
                plan=plan,
                workflow_run_id=run_id,
                normalized_data=normalized_data,
                backend_endpoint=backend_endpoint,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Lines busy: provider couldn't answer run {run_id}: {e}")
            await finish_turned_away_call(run_id)
            return _busy_line(provider_class)
    except Exception as e:  # noqa: BLE001 - the caller still hears the busy line
        logger.error(f"Lines busy: falling back to the busy line: {e}")
        return _busy_line(provider_class)

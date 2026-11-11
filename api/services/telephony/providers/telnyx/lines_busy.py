"""Call Control for a caller who rang while every line was busy.

Telnyx ignores webhook response bodies (there is no TeXML on these
numbers: they run on a Call Control application), so the plan is carried
out with commands on the call, one step per event, all sent to
``/telnyx/lines-busy/{run}``:

1. ``answer`` (no media stream) - in ``TelnyxProvider.lines_busy_response``;
2. ``call.answered``: ``speak`` the line for the plan;
3. ``call.speak.ended``: ``transfer`` to the team (forward), ``record_start``
   (voicemail, with a beep, capped) or ``hangup`` (busy line);
4. forward: ``call.bridged`` on the caller's leg means someone answered; a
   ``call.hangup`` on the team's leg without that means nobody did, and the
   caller is asked for a voicemail instead;
5. ``call.recording.saved``: the file is kept as the call's recording, then
   a goodbye and ``hangup``;
6. ``call.hangup`` on the caller's leg: the call is finished.

Each command carries ``client_state`` naming the step, which Telnyx sends
back on the events that follow. Docs:
https://developers.telnyx.com/api-reference/call-commands/answer-call
https://developers.telnyx.com/api-reference/call-commands/speak-text
https://developers.telnyx.com/api-reference/call-commands/transfer-call
https://developers.telnyx.com/api-reference/call-commands/start-recording
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Mapping

from loguru import logger

from api.errors.telephony_errors import CALLER_LINES_BUSY
from api.services.calls.lines_busy import (
    FORWARD_FAILED_VOICEMAIL_LINE,
    FORWARD_KEY,
    FORWARD_LINE,
    FORWARD_RING_SECONDS,
    MAX_VOICEMAIL_SECONDS,
    NO_MESSAGE_GOODBYE,
    VOICEMAIL_LINE,
    VOICEMAIL_THANKS,
    LinesBusyAction,
    forward_answered,
    forward_record,
)

# Steps, sent as client_state.
GREET_FORWARD = "forward"
GREET_VOICEMAIL = "voicemail"
GREET_BUSY = "busy"
RECORDING = "recording"
GOODBYE = "goodbye"

SPEAK_VOICE = {"voice": "female", "language": "en-GB"}


def events_url(backend_endpoint: str, workflow_run_id: int) -> str:
    from api.services.telephony import ws_auth

    url = f"{backend_endpoint}/api/v1/telephony/telnyx/lines-busy/{workflow_run_id}"
    token = ws_auth.mint_events_token(workflow_run_id)
    return f"{url}?token={token}" if token else url


def encode_state(step: str) -> str:
    return base64.b64encode(step.encode()).decode()


def decode_state(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def greeting(action: LinesBusyAction) -> tuple[str, str]:
    """The first line the caller hears, and its step."""
    if action == LinesBusyAction.FORWARD:
        return FORWARD_LINE, GREET_FORWARD
    if action == LinesBusyAction.VOICEMAIL:
        return VOICEMAIL_LINE, GREET_VOICEMAIL
    return CALLER_LINES_BUSY, GREET_BUSY


def speak_payload(text: str, step: str) -> dict[str, Any]:
    return {"payload": text, **SPEAK_VOICE, "client_state": encode_state(step)}


def record_payload() -> dict[str, Any]:
    return {
        "format": "wav",
        "channels": "single",
        "play_beep": True,
        "max_length": MAX_VOICEMAIL_SECONDS,
        "timeout_secs": 10,
        "client_state": encode_state(RECORDING),
    }


def transfer_payload(destination: str, webhook_url: str) -> dict[str, Any]:
    # No "from": Telnyx presents the caller's own number to the team.
    return {
        "to": destination,
        "timeout_secs": FORWARD_RING_SECONDS,
        "webhook_url": webhook_url,
        "webhook_url_method": "POST",
        "client_state": encode_state(GREET_FORWARD),
    }


def _seconds_between(start: Any, end: Any) -> int:
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, round((b - a).total_seconds()))


async def handle_event(
    provider,
    run,
    event: Mapping[str, Any],
    *,
    backend_endpoint: str,
) -> str:
    """Carry the plan one step further. Returns what was done (for logs and
    tests)."""
    from api.services.telephony.lines_busy import (
        finish_turned_away_call,
        note_forward_result,
        store_voicemail,
        stored_plan,
    )

    data = event.get("data") or {}
    from api.services.telephony.providers.telnyx.provider import normalize_event_type

    event_type = normalize_event_type(data.get("event_type", ""))
    payload = data.get("payload") or {}
    gathered = run.gathered_context or {}
    caller_leg = gathered.get("call_id")
    leg = payload.get("call_control_id")
    plan = stored_plan(run)
    if plan is None or not caller_leg:
        return "ignored"
    step = decode_state(payload.get("client_state"))

    if leg != caller_leg:
        # The team's phone (forward). Only its end matters: without a
        # bridge first, nobody picked up.
        if event_type != "call.hangup" or forward_answered(gathered):
            return "ignored"
        if FORWARD_KEY in gathered:
            return "ignored"
        take_message = plan.voicemail_fallback
        await note_forward_result(
            run.id,
            forward_record(payload.get("hangup_cause") or "no_answer"),
            finished=not take_message,
        )
        if take_message:
            await provider.call_command(
                caller_leg,
                "speak",
                speak_payload(FORWARD_FAILED_VOICEMAIL_LINE, GREET_VOICEMAIL),
            )
            return "voicemail_after_forward"
        await provider.call_command(
            caller_leg, "speak", speak_payload(CALLER_LINES_BUSY, GREET_BUSY)
        )
        return "busy_after_forward"

    if event_type == "call.answered":
        text, greet = greeting(plan.action)
        await provider.call_command(caller_leg, "speak", speak_payload(text, greet))
        return f"speak:{greet}"

    if event_type == "call.speak.ended":
        if step == GREET_FORWARD and plan.destination:
            await provider.call_command(
                caller_leg,
                "transfer",
                transfer_payload(
                    plan.destination, events_url(backend_endpoint, run.id)
                ),
            )
            return "transfer"
        if step == GREET_VOICEMAIL:
            await provider.call_command(caller_leg, "record_start", record_payload())
            return "record"
        await provider.call_command(caller_leg, "hangup", {})
        return "hangup"

    if event_type == "call.bridged":
        if not forward_answered(gathered):
            await note_forward_result(run.id, forward_record("bridged"), finished=False)
        return "forward_answered"

    if event_type == "call.recording.saved":
        urls = payload.get("recording_urls") or {}
        url = urls.get("wav") if isinstance(urls, Mapping) else None
        seconds = _seconds_between(
            payload.get("recording_started_at"), payload.get("recording_ended_at")
        )
        audio = await provider.download_recording(url) if url else None
        stored = await store_voicemail(run.id, audio, seconds)
        if stored:
            await provider.delete_recording(payload.get("recording_id"))
        # The caller may still be on the line (the message hit the cap).
        await provider.call_command(
            caller_leg,
            "speak",
            speak_payload(VOICEMAIL_THANKS if stored else NO_MESSAGE_GOODBYE, GOODBYE),
            quiet=True,
        )
        return "voicemail_stored" if stored else "voicemail_empty"

    if event_type == "call.hangup":
        await finish_turned_away_call(run.id)
        return "finished"

    logger.debug(f"[run {run.id}] Lines busy: Telnyx {event_type} ignored")
    return "ignored"

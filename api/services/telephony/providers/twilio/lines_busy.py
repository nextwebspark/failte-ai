"""TwiML for a caller who rang while every line was busy.

Forward: ``<Say>`` then ``<Dial>`` the team's number; Twilio requests the
Dial's ``action`` when it ends, with ``DialCallStatus`` (``completed`` or
``answered``: someone picked up; ``busy``, ``no-answer``, ``failed``,
``canceled``: nobody did). Nobody picked up: a voicemail.
https://www.twilio.com/docs/voice/twiml/dial#action

Voicemail: ``<Say>`` then ``<Record>``. Twilio requests ``action`` when the
recording ends (also when the caller hangs up), and
``recordingStatusCallback`` once the file is ready to download; with an
empty recording it skips ``action`` and goes on to the next verb, our
``<Redirect>`` to the same ``action`` with ``empty=1``.
https://www.twilio.com/docs/voice/twiml/record

The callbacks are signed by Twilio (``X-Twilio-Signature``) and checked in
``routes.py`` like every other Twilio callback.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from api.errors.telephony_errors import CALLER_LINES_BUSY
from api.services.calls.lines_busy import (
    FORWARD_FAILED_VOICEMAIL_LINE,
    FORWARD_LINE,
    FORWARD_RING_SECONDS,
    MAX_VOICEMAIL_SECONDS,
    NO_MESSAGE_GOODBYE,
    VOICEMAIL_LINE,
    VOICEMAIL_THANKS,
)

_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'
# Twilio's dial results that mean someone on the team picked up.
ANSWERED_STATUSES = frozenset({"completed", "answered"})


def callback_url(backend_endpoint: str, workflow_run_id: int, name: str) -> str:
    return (
        f"{backend_endpoint}/api/v1/telephony/twilio/lines-busy/"
        f"{workflow_run_id}/{name}"
    )


def _say(text: str) -> str:
    return f'    <Say voice="alice">{escape(text)}</Say>\n'


def _response(body: str) -> str:
    return f"{_HEAD}<Response>\n{body}</Response>"


def forward_twiml(backend_endpoint: str, workflow_run_id: int, destination: str) -> str:
    action = callback_url(backend_endpoint, workflow_run_id, "dial-result")
    # No callerId: Twilio shows the caller's own number on the team's phone.
    return _response(
        _say(FORWARD_LINE)
        + f"    <Dial timeout={quoteattr(str(FORWARD_RING_SECONDS))} "
        f'answerOnBridge="true" action={quoteattr(action)} method="POST">'
        f"<Number>{escape(destination)}</Number></Dial>\n"
    )


def voicemail_twiml(
    backend_endpoint: str, workflow_run_id: int, *, after_forward: bool = False
) -> str:
    done = callback_url(backend_endpoint, workflow_run_id, "voicemail-done")
    recording = callback_url(backend_endpoint, workflow_run_id, "recording")
    line = FORWARD_FAILED_VOICEMAIL_LINE if after_forward else VOICEMAIL_LINE
    return _response(
        _say(line) + f"    <Record maxLength={quoteattr(str(MAX_VOICEMAIL_SECONDS))} "
        'playBeep="true" timeout="5" finishOnKey="#" '
        f'action={quoteattr(done)} method="POST" '
        f"recordingStatusCallback={quoteattr(recording)} "
        'recordingStatusCallbackMethod="POST" '
        'recordingStatusCallbackEvent="completed"/>\n'
        f'    <Redirect method="POST">{escape(done)}?empty=1</Redirect>\n'
    )


def busy_twiml() -> str:
    return _response(_say(CALLER_LINES_BUSY) + "    <Hangup/>\n")


def goodbye_twiml(*, left_message: bool) -> str:
    return _response(
        _say(VOICEMAIL_THANKS if left_message else NO_MESSAGE_GOODBYE)
        + "    <Hangup/>\n"
    )


def hangup_twiml() -> str:
    return _response("    <Hangup/>\n")

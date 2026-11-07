"""Custom voices: an owner who already has a cloned voice (ElevenLabs,
Cartesia…) asks LightMove to set it up for their agent.

Customers can't store their own provider keys on the platform, and LightMove
only offers Google voices, so this is a request the team handles by hand:
the owner names the provider and voice ID and confirms consent; the request
is stored on the workspace and emailed to the operators. No key is ever
asked for or accepted.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from html import escape
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from api.db import db_client
from api.enums import OrganizationConfigurationKey

REQUESTS_KEY = OrganizationConfigurationKey.CUSTOM_VOICE_REQUESTS.value
# Kept per workspace; older ones drop off.
MAX_STORED = 50

VoiceProvider = Literal["elevenlabs", "cartesia", "other"]
PROVIDER_LABELS: dict[str, str] = {
    "elevenlabs": "ElevenLabs",
    "cartesia": "Cartesia",
    "other": "Another provider",
}


class CustomVoiceRequestIn(BaseModel):
    provider: VoiceProvider
    voice_id: str = Field(min_length=1, max_length=200)
    voice_name: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    # "This is my own voice, or I have the speaker's written permission."
    consent: bool

    @field_validator("voice_id", "voice_name", "note")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("voice_id")
    @classmethod
    def _not_a_key(cls, value: str | None) -> str | None:
        # A voice ID is short and has no spaces; refuse what looks like an API key.
        if not value:
            raise ValueError("Enter the voice ID.")
        if value.lower().startswith(("sk_", "sk-")) or " " in value:
            raise ValueError(
                "That looks like an API key, not a voice ID. Please don't send keys."
            )
        return value


class CustomVoiceRequest(BaseModel):
    workflow_id: int
    provider: VoiceProvider
    voice_id: str
    voice_name: str | None = None
    note: str | None = None
    requested_by: str | None = None
    requested_at: datetime
    status: Literal["requested", "set_up", "declined"] = "requested"


class ConsentRequiredError(ValueError):
    pass


def operator_recipients(env: dict[str, str] | None = None) -> list[str]:
    """Who hears about requests: VOICE_REQUEST_EMAILS, else the operators'
    alert addresses (OPERATOR_ALERT_EMAILS)."""
    env = env if env is not None else dict(os.environ)
    raw = env.get("VOICE_REQUEST_EMAILS") or env.get("OPERATOR_ALERT_EMAILS") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _stored(organization_id: int) -> list[dict[str, Any]]:
    row = await db_client.get_configuration(organization_id, REQUESTS_KEY)
    value = row.value if row is not None else None
    items = value.get("requests") if isinstance(value, dict) else None
    return list(items) if isinstance(items, list) else []


async def latest_request(
    organization_id: int, workflow_id: int
) -> CustomVoiceRequest | None:
    for item in reversed(await _stored(organization_id)):
        if isinstance(item, dict) and item.get("workflow_id") == workflow_id:
            try:
                return CustomVoiceRequest.model_validate(item)
            except ValueError:
                return None
    return None


async def submit_request(
    *,
    organization_id: int,
    organization_name: str | None,
    workflow_id: int,
    workflow_name: str | None,
    requested_by: str | None,
    body: CustomVoiceRequestIn,
    now: datetime | None = None,
) -> CustomVoiceRequest:
    if not body.consent:
        raise ConsentRequiredError(
            "Please confirm it's your own voice or you have the speaker's permission."
        )
    request = CustomVoiceRequest(
        workflow_id=workflow_id,
        provider=body.provider,
        voice_id=body.voice_id,
        voice_name=body.voice_name,
        note=body.note,
        requested_by=requested_by,
        requested_at=now or datetime.now(UTC),
    )
    items = await _stored(organization_id)
    items.append(request.model_dump(mode="json"))
    await db_client.upsert_configuration(
        organization_id, REQUESTS_KEY, {"requests": items[-MAX_STORED:]}
    )
    await _notify(request, organization_id, organization_name, workflow_name)
    return request


def request_email_lines(
    request: CustomVoiceRequest,
    organization_id: int,
    organization_name: str | None,
    workflow_name: str | None,
) -> list[str]:
    return [
        f"Workspace: {organization_name or '-'} (id {organization_id})",
        f"Agent: {workflow_name or '-'} (id {request.workflow_id})",
        f"Provider: {PROVIDER_LABELS.get(request.provider, request.provider)}",
        f"Voice ID: {request.voice_id}",
        f"Voice name: {request.voice_name or '-'}",
        f"Asked by: {request.requested_by or '-'}",
        f"Note: {request.note or '-'}",
        "Consent confirmed: yes (own voice, or written permission from the speaker).",
    ]


async def _notify(
    request: CustomVoiceRequest,
    organization_id: int,
    organization_name: str | None,
    workflow_name: str | None,
) -> None:
    """Email the operators. Never raises: the request is already stored."""
    recipients = operator_recipients()
    if not recipients:
        logger.warning(
            f"Custom voice request stored for org {organization_id}, but no "
            "VOICE_REQUEST_EMAILS or OPERATOR_ALERT_EMAILS is set, so nobody was emailed"
        )
        return
    from api.services.email import get_email_sender
    from api.services.email.base import EmailMessage

    lines = request_email_lines(
        request, organization_id, organization_name, workflow_name
    )
    sender = get_email_sender()
    for to in recipients:
        try:
            await sender.send(
                EmailMessage(
                    to=to,
                    subject=f"Custom voice request: {organization_name or organization_id}",
                    text="\n".join(lines) + "\n",
                    html="".join(f"<p>{escape(line)}</p>" for line in lines),
                )
            )
        except Exception as exc:  # noqa: BLE001 - the request is stored either way
            logger.warning(
                f"Could not email the custom voice request: {type(exc).__name__}"
            )

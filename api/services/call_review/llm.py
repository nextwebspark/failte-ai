"""The one model call behind a call review: Gemini on the platform's Vertex
project, JSON out against a strict schema."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from api.services.configuration.platform.policy import (
    platform_settings_for_organization,
)
from api.services.configuration.platform.settings import PlatformVertexSettings

if TYPE_CHECKING:
    from google import genai

# The cheapest, fastest text model the platform offers (see
# configuration/platform/catalog.py LLM_MODELS).
REVIEW_MODEL: Final = "gemini-3.1-flash-lite"
REVIEW_TEMPERATURE: Final = 0.1
REVIEW_MAX_OUTPUT_TOKENS: Final = 400
REVIEW_TIMEOUT_SECS: Final = 25.0


@dataclass(frozen=True, slots=True)
class ReviewAnswer:
    text: str
    model: str
    prompt_tokens: int | None
    output_tokens: int | None


# One client per Vertex placement: each owns a connection pool.
_CLIENTS: dict[tuple[str, str, str | None], "genai.Client"] = {}


def _credentials(credentials_json: str | None) -> Any:
    if not credentials_json:
        return None
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
        json.loads(credentials_json),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _client(settings: PlatformVertexSettings) -> "genai.Client":
    key = (settings.project_id, settings.llm_location, settings.credentials_json)
    client = _CLIENTS.get(key)
    if client is None:
        from google import genai

        client = genai.Client(
            vertexai=True,
            project=settings.project_id,
            location=settings.llm_location,
            credentials=_credentials(settings.credentials_json),
        )
        _CLIENTS[key] = client
    return client


async def ask_reviewer(
    *,
    organization_id: int,
    system: str,
    user: str,
    schema: dict[str, Any],
    model: str = REVIEW_MODEL,
    temperature: float = REVIEW_TEMPERATURE,
    max_output_tokens: int = REVIEW_MAX_OUTPUT_TOKENS,
) -> ReviewAnswer:
    """One JSON answer from the model. Raises on any failure (no settings,
    timeout, API error, empty answer); the caller decides what that means."""
    from google.genai import types

    settings = await platform_settings_for_organization(organization_id)
    client = _client(settings)
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
        response_schema=schema,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response = await asyncio.wait_for(
        client.aio.models.generate_content(model=model, contents=user, config=config),
        REVIEW_TIMEOUT_SECS,
    )
    if not response.text:
        raise ValueError("empty answer")
    usage = response.usage_metadata
    return ReviewAnswer(
        text=response.text,
        model=model,
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
    )

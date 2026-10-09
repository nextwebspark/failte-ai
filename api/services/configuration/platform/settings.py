"""Server-side Vertex settings that platform configurations compile against."""

from __future__ import annotations

from dataclasses import dataclass

from api import constants


class PlatformModelsNotConfiguredError(ValueError):
    """Platform models were used on a server without a Vertex project."""


@dataclass(frozen=True, slots=True)
class PlatformVertexSettings:
    project_id: str
    llm_location: str
    realtime_location: str
    speech_location: str
    # None means Application Default Credentials.
    credentials_json: str | None = None


def load_platform_vertex_settings() -> PlatformVertexSettings:
    """Read the operator's Vertex settings from the environment.

    Raises PlatformModelsNotConfiguredError when no project is configured, so a
    platform configuration on a misconfigured server fails loudly instead of
    building services that cannot authenticate.
    """
    if not constants.PLATFORM_VERTEX_PROJECT_ID:
        raise PlatformModelsNotConfiguredError(
            "Platform models are not configured on this server: "
            "set PLATFORM_VERTEX_PROJECT_ID"
        )
    return PlatformVertexSettings(
        project_id=constants.PLATFORM_VERTEX_PROJECT_ID,
        llm_location=constants.PLATFORM_VERTEX_LLM_LOCATION,
        realtime_location=constants.PLATFORM_VERTEX_REALTIME_LOCATION,
        speech_location=constants.PLATFORM_GOOGLE_SPEECH_LOCATION,
        credentials_json=constants.PLATFORM_GOOGLE_CREDENTIALS_JSON,
    )

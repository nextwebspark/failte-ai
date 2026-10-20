"""Global CORS policy for the API (see ``api/app.py``).

The widget's public embed endpoints are not governed by this: they reflect the
caller's origin themselves, gated by each embed token's allowed domains
(``PublicEmbedCORSMiddleware`` in ``api/routes/public_embed.py``), so customer
sites keep working whatever this allowlist says.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from api.enums import Environment


class CorsConfigurationError(RuntimeError):
    """The API must not start with this CORS configuration."""


@dataclass(frozen=True, slots=True)
class CorsSettings:
    allow_origins: list[str]
    allow_credentials: bool


def origin_of(url: str) -> str | None:
    """``scheme://host[:port]`` of ``url``, or ``None`` if it has neither."""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def resolve_cors_settings(
    *,
    deployment_mode: str,
    environment: str,
    allowed_origins: list[str],
    public_base_url: str | None,
) -> CorsSettings:
    """Pick the global CORS policy.

    - ``CORS_ALLOWED_ORIGINS`` set: that explicit allowlist, with credentials,
      in every mode. ``*`` is refused.
    - Production (``ENVIRONMENT=production``) without it: the origin of
      ``PUBLIC_BASE_URL``; neither set refuses to start. Production never
      answers ``*``.
    - Outside OSS mode without it: refuse to start (unchanged).
    - Local OSS development: ``*`` without credentials, as before. UI and API
      usually share one origin behind a proxy, where CORS does not apply.
    """
    if "*" in allowed_origins:
        raise CorsConfigurationError(
            "CORS_ALLOWED_ORIGINS cannot contain '*' with credentialed requests"
        )
    if allowed_origins:
        return CorsSettings(
            allow_origins=[o.rstrip("/") for o in allowed_origins],
            allow_credentials=True,
        )
    if environment == Environment.PRODUCTION.value:
        origin = origin_of(public_base_url or "")
        if origin is None:
            raise CorsConfigurationError(
                "Set CORS_ALLOWED_ORIGINS (or PUBLIC_BASE_URL) when ENVIRONMENT "
                "is 'production'; production never allows every origin."
            )
        return CorsSettings(allow_origins=[origin], allow_credentials=True)
    if deployment_mode != "oss":
        raise CorsConfigurationError(
            "CORS_ALLOWED_ORIGINS must be set to an explicit origin allowlist "
            "when DEPLOYMENT_MODE != 'oss'"
        )
    return CorsSettings(allow_origins=["*"], allow_credentials=False)

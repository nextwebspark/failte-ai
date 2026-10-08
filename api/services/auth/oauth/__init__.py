from pydantic import SecretStr

from api.constants import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
from api.services.auth.oauth.base import (
    AuthorizationRequest,
    OAuthIdentity,
    OAuthProvider,
)
from api.services.auth.oauth.google import GoogleOAuthProvider


def google_oauth_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_google_oauth_provider() -> OAuthProvider | None:
    """FastAPI dependency; None when Google login is not configured."""
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        return None
    return GoogleOAuthProvider(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=SecretStr(GOOGLE_CLIENT_SECRET),
        redirect_uri=GOOGLE_REDIRECT_URI,
    )


__all__ = [
    "AuthorizationRequest",
    "OAuthIdentity",
    "OAuthProvider",
    "get_google_oauth_provider",
    "google_oauth_enabled",
]

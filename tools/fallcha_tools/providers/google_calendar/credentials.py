"""Google credential sources, shared by every Google provider.

Kept as a module so existing imports keep working; the implementation lives
in :mod:`fallcha_tools.providers.google_common.credentials`.
"""

from __future__ import annotations

from fallcha_tools.providers.google_common.credentials import (
    ASSERTION_LIFETIME,
    GOOGLE_TOKEN_URL,
    JWT_BEARER_GRANT,
    REFRESH_MARGIN,
    CachedToken,
    CacheKey,
    Clock,
    GoogleCredentialsSource,
    OAuthCredentials,
    ServiceAccountCredentials,
    ServiceAccountSigner,
    SignerCache,
    TokenCache,
    utc_now,
)

__all__ = [
    "ASSERTION_LIFETIME",
    "GOOGLE_TOKEN_URL",
    "JWT_BEARER_GRANT",
    "REFRESH_MARGIN",
    "CacheKey",
    "CachedToken",
    "Clock",
    "GoogleCredentialsSource",
    "OAuthCredentials",
    "ServiceAccountCredentials",
    "ServiceAccountSigner",
    "SignerCache",
    "TokenCache",
    "utc_now",
]

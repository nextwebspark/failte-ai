"""Keep OAuth callback query strings (authorization code, state) out of the
uvicorn access log."""

from __future__ import annotations

import logging

ACCESS_LOGGER = "uvicorn.access"
_CALLBACK_PREFIX = "/oauth/"


class RedactOAuthQuery(logging.Filter):
    """Drops the query string of ``/oauth/*`` requests from access records.

    uvicorn logs ``(client, method, full_path, http_version, status)``; the
    path is rewritten in place, so every handler sees the redacted form.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if _CALLBACK_PREFIX in path and "?" in path:
                record.args = (
                    *args[:2],
                    path.split("?", 1)[0] + "?<redacted>",
                    *args[3:],
                )
        return True


def install_access_log_filter() -> None:
    """Idempotent: safe to call once per app instance."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, RedactOAuthQuery) for f in access.filters):
        access.addFilter(RedactOAuthQuery())

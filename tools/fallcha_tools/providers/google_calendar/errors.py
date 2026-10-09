"""Failures surfaced to the agent (MCP) or the HTTP caller (REST).

Every message is safe to show: no tokens, keys or raw Google bodies.
"""

from __future__ import annotations

from fallcha_tools.core.errors import ToolsError


class CalendarToolError(ToolsError):
    """Base class; the message is shown to the caller verbatim."""


class BadArgumentError(CalendarToolError):
    """The caller passed an unusable argument (REST: 400)."""


class NotConfiguredError(CalendarToolError):
    """The connection lacks settings this function needs (REST: 409)."""


class GoogleApiError(CalendarToolError):
    """Google refused, failed or timed out (REST: 502)."""

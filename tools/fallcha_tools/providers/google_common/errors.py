"""Failures surfaced to the agent (MCP) or the HTTP caller (REST) by every
Google provider.

Every message is safe to show: no tokens, keys or raw Google bodies.
"""

from __future__ import annotations

from fallcha_tools.core.errors import ToolsError


class GoogleToolError(ToolsError):
    """Base class; the message is shown to the caller verbatim."""


class BadArgumentError(GoogleToolError):
    """The caller passed an unusable argument (REST: 400)."""


class NotConfiguredError(GoogleToolError):
    """The connection lacks settings this function needs (REST: 409)."""


class GoogleApiError(GoogleToolError):
    """Google refused, failed or timed out (REST: 502).

    ``access_problem`` is set for "not shared / not found" failures to the bare
    problem (e.g. "the calendar was not found"), so an admin, but not a
    caller, can be told which Google account needs access.
    ``retryable`` marks failures where Google may still have acted (timeouts,
    network errors), so a write must be retried rather than assumed lost.
    """

    def __init__(
        self,
        message: str,
        *,
        access_problem: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.access_problem = access_problem
        self.retryable = retryable

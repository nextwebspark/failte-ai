"""Calendar failures: the shared Google error classes under their old names."""

from __future__ import annotations

from fallcha_tools.providers.google_common.errors import (
    BadArgumentError,
    GoogleApiError,
    GoogleToolError,
    NotConfiguredError,
)

# The calendar's base class is the shared Google one, so ``except
# CalendarToolError`` also covers errors raised by the shared plumbing.
CalendarToolError = GoogleToolError

__all__ = [
    "BadArgumentError",
    "CalendarToolError",
    "GoogleApiError",
    "NotConfiguredError",
]

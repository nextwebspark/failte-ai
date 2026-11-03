"""Narrow interfaces the call summary notifier depends on.

``api.db.db_client`` satisfies ``CallSummaryStore`` structurally; tests pass in
fakes.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from api.db.call_summary_client import CallSummaryRun


class CallSummaryStore(Protocol):
    async def get_call_summary_run(self, run_id: int) -> CallSummaryRun | None: ...

    async def claim_call_summary_email(
        self, run_id: int, claimed_at: datetime
    ) -> bool: ...


# The IANA timezone an organization works in, or None when it set none.
TimezoneLookup = Callable[[int], Awaitable[str | None]]

"""Read-only order lookup against a Google Sheet (ported from the shim).

Security posture, deliberate:

- Tokens for the sheet are minted with ``spreadsheets.readonly`` only, and the
  sheet should be shared with the service account as Viewer: two independent
  reasons the agent cannot alter an order.
- A caller must clear BOTH a name check and an address/eircode check before
  any order data is returned. A failed match returns the same answer whether
  the name, the address, or the customer is wrong, so the function cannot be
  used to enumerate customers.
- The response carries only what a person needs on the phone; never the phone
  number, the full address or internal notes.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from fallcha_tools.providers.google_calendar.errors import GoogleApiError
from fallcha_tools.providers.google_calendar.schemas import OrderLookupResult

ADDRESS_MATCH_THRESHOLD = 0.62
NAME_MATCH_THRESHOLD = 0.72
CACHE_TTL = timedelta(seconds=60)
MAX_CACHED_SHEETS = 256
SHEET_COLUMNS = "A1:Z1000"
NOT_VERIFIED = (
    "I could not match those details to an order. Could you give me "
    "the name exactly as it is on the account, and the Eircode?"
)

Row = Mapping[str, str]

_FILLER = re.compile(r"\b(number|no|apt|apartment|the|street|st|road|rd|avenue|ave)\b")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation and filler so spoken input can be compared."""
    text = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    text = _FILLER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def name_score(row: Row, spoken_name: str) -> float:
    """Score a spoken name against the row, allowing surname-only answers."""
    stored = row.get("customer_name", "")
    best = similar(stored, spoken_name)
    spoken_parts = normalise(spoken_name).split()
    for part in normalise(stored).split():
        for said in spoken_parts:
            if len(part) > 3 and len(said) > 3:
                best = max(best, SequenceMatcher(None, part, said).ratio())
    return best


def address_score(row: Row, spoken_address: str) -> float:
    """Eircode is the strongest signal; fall back to the street address."""
    said = normalise(spoken_address)
    eircode = normalise(row.get("eircode", ""))
    if eircode and eircode.replace(" ", "") in said.replace(" ", ""):
        return 1.0
    score = similar(row.get("address", ""), spoken_address)
    # Any distinctive token from the address (house name, town) carries weight.
    for token in normalise(row.get("address", "")).split():
        if len(token) > 4 and token in said:
            score = max(score, 0.8)
    return score


def rows_from_values(values: Sequence[Sequence[str]]) -> list[dict[str, str]]:
    """Header row + data rows -> dicts; blank rows are skipped."""
    if not values:
        raise GoogleApiError("the orders sheet is empty")
    header = [cell.strip() for cell in values[0]]
    return [
        dict(zip(header, [*row, *([""] * (len(header) - len(row)))], strict=False))
        for row in values[1:]
        if any(cell.strip() for cell in row)
    ]


def match_order(
    rows: Sequence[Row],
    spoken_name: str,
    spoken_address: str,
    order_id: str | None = None,
) -> OrderLookupResult:
    candidates = list(rows)
    if order_id:
        wanted = normalise(order_id).replace(" ", "")
        by_id = [
            r
            for r in candidates
            if normalise(r.get("order_id", "")).replace(" ", "") == wanted
        ]
        candidates = by_id or candidates

    scored = sorted(
        (
            (name_score(r, spoken_name), address_score(r, spoken_address), r)
            for r in candidates
        ),
        key=lambda item: item[0] + item[1],
        reverse=True,
    )
    if not scored:
        return OrderLookupResult(verified=False, say=NOT_VERIFIED)
    best_name, best_address, row = scored[0]
    if best_name < NAME_MATCH_THRESHOLD or best_address < ADDRESS_MATCH_THRESHOLD:
        # Same answer whatever did not match. Do not leak which.
        return OrderLookupResult(verified=False, say=NOT_VERIFIED)

    def field(name: str) -> str:
        return row.get(name, "").strip()

    say = (
        f"I have your order for the {field('package')}. "
        f"The status is: {field('status')}."
    )
    if field("eta"):
        say += f" {field('eta')}."
    return OrderLookupResult(
        verified=True,
        order_id=field("order_id"),
        customer_name=field("customer_name"),
        package=field("package"),
        hardware=field("hardware"),
        status=field("status"),
        eta=field("eta"),
        order_date=field("order_date"),
        monthly_price=field("monthly_price"),
        say=say,
    )


@dataclass(frozen=True, slots=True)
class _CachedRows:
    rows: list[dict[str, str]]
    fetched_at: datetime


OrdersKey = tuple[uuid.UUID, str, str]


class OrdersCache:
    """Per-connection, per-sheet row cache, so a busy call does not re-fetch."""

    def __init__(
        self, ttl: timedelta = CACHE_TTL, max_entries: int = MAX_CACHED_SHEETS
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._entries: dict[OrdersKey, _CachedRows] = {}

    def __len__(self) -> int:
        return len(self._entries)

    async def rows(
        self,
        key: OrdersKey,
        now: datetime,
        fetch: Callable[[], Awaitable[list[dict[str, str]]]],
    ) -> list[dict[str, str]]:
        cached = self._entries.get(key)
        if cached is not None and now - cached.fetched_at < self._ttl:
            return cached.rows
        rows = await fetch()
        self._entries[key] = _CachedRows(rows=rows, fetched_at=now)
        self._evict(now)
        return rows

    def _evict(self, now: datetime) -> None:
        """Drop stale sheets, then the oldest ones beyond ``max_entries``."""
        for stale in [
            k for k, v in self._entries.items() if now - v.fetched_at >= self._ttl
        ]:
            del self._entries[stale]
        overflow = len(self._entries) - self._max_entries
        if overflow > 0:
            oldest = sorted(self._entries, key=lambda k: self._entries[k].fetched_at)
            for stale in oldest[:overflow]:
                del self._entries[stale]

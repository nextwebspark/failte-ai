"""The Sheets use cases behind the MCP tools.

Every tool call runs under one time budget (5 s by default): a voice turn
cannot wait longer, and a call that started late never starts another
request it cannot finish.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fallcha_tools.core.provider import ConnectionContext
from fallcha_tools.providers.google_common.credentials import Clock, utc_now
from fallcha_tools.providers.google_common.errors import (
    BadArgumentError,
    GoogleApiError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_common.http import Budget
from fallcha_tools.providers.google_sheets.cells import (
    column_letter,
    find_column,
    header_names,
    neutralize_formula,
    normalize,
    quote_tab,
    row_dict,
    rows_range,
    updated_row_number,
)
from fallcha_tools.providers.google_sheets.client import (
    SheetsClient,
    SpreadsheetInfo,
)
from fallcha_tools.providers.google_sheets.orders import (
    SHEET_COLUMNS,
    SHEET_ROWS,
    OrdersCache,
    match_order,
    order_rows,
)
from fallcha_tools.providers.google_sheets.schemas import (
    AppendRowResult,
    FindRowsResult,
    GetRowResult,
    OrderLookupResult,
    SheetRow,
)
from fallcha_tools.providers.google_sheets.settings import SheetsConfig, same_tab

DEFAULT_DEADLINE_SECONDS = 5.0
DEADLINE_GRACE = 0.25
# A follow-up request is only started with at least this much time left.
MIN_REQUEST_SECONDS = 0.5
# find_rows scans at most this many rows below the header.
MAX_SCAN_ROWS = 10_000
_MAX_LISTED_COLUMNS = 20
APPEND_UNCONFIRMED = (
    "Google did not confirm the row was added; check the sheet before adding it again"
)


def _column_list(headers: list[str]) -> str:
    shown = ", ".join(headers[:_MAX_LISTED_COLUMNS])
    return shown + (", ..." if len(headers) > _MAX_LISTED_COLUMNS else "")


ServiceFactory = Callable[[ConnectionContext], "SheetsService"]


@dataclass(frozen=True, slots=True)
class SheetsService:
    client: SheetsClient
    config: SheetsConfig
    connection_id: uuid.UUID
    orders_cache: OrdersCache
    clock: Clock = utc_now
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS

    @asynccontextmanager
    async def _deadline(self) -> AsyncIterator[None]:
        """A hard stop slightly after the budget, in case a request outlives
        its own timeout (e.g. a slow token refresh)."""
        try:
            async with asyncio.timeout(self.deadline_seconds + DEADLINE_GRACE):
                yield
        except TimeoutError:
            raise GoogleApiError(
                "Google did not respond in time", retryable=True
            ) from None

    def _budget(self) -> Budget:
        return Budget.starting_now(
            self.deadline_seconds, min_seconds=MIN_REQUEST_SECONDS
        )

    # -- tools -------------------------------------------------------------

    async def find_rows(
        self, column: str, value: str, tab: str | None, match: str
    ) -> FindRowsResult:
        async with self._deadline():
            return await self._find_rows(column, value, tab, match)

    async def get_row(self, row_number: int, tab: str | None) -> GetRowResult:
        async with self._deadline():
            return await self._get_row(row_number, tab)

    async def append_row(
        self, values: Mapping[str, str], tab: str | None
    ) -> AppendRowResult:
        try:
            async with self._deadline():
                return await self._append_row(values, tab)
        except GoogleApiError as exc:
            if exc.retryable:  # Google may have written the row
                raise GoogleApiError(APPEND_UNCONFIRMED, retryable=True) from None
            raise

    async def look_up_order(
        self, caller_name: str, address_or_eircode: str, order_id: str | None = None
    ) -> OrderLookupResult:
        """Verified, read-only order lookup (see ``orders``)."""
        tab = self.config.orders_tab
        if not tab:
            raise NotConfiguredError("order lookup is not set up for this connection")
        sheet_id = self.config.spreadsheet_id
        first = self.config.header_row
        a1 = f"{quote_tab(tab)}!A{first}:{SHEET_COLUMNS}{first + SHEET_ROWS - 1}"

        async def fetch() -> list[dict[str, str]]:
            [values] = await self.client.read_ranges(
                sheet_id, [a1], budget=self._budget(), read_only=True
            )
            return order_rows(values, self.config.order_columns)

        async with self._deadline():
            rows = await self.orders_cache.rows(
                (self.connection_id, sheet_id, tab), self.clock(), fetch
            )
        return match_order(rows, caller_name, address_or_eircode, order_id)

    async def _find_rows(
        self, column: str, value: str, tab: str | None, match: str
    ) -> FindRowsResult:
        budget = self._budget()
        name = await self._tab(tab, budget)
        header_row = self.config.header_row
        [values] = await self.client.read_ranges(
            self.config.spreadsheet_id,
            [rows_range(name, header_row, header_row + MAX_SCAN_ROWS)],
            budget=budget,
        )
        headers = header_names(values[0]) if values else []
        index = find_column(headers, column)
        if index is None:
            raise BadArgumentError(self._unknown_column(column, headers))
        wanted = normalize(value)
        limit = self.config.max_rows_returned
        rows: list[SheetRow] = []
        matched = 0
        for offset, row in enumerate(values[1:], start=1):
            cell = normalize(row[index]) if index < len(row) else ""
            hit = cell == wanted if match == "exact" else wanted in cell
            if not hit:
                continue
            matched += 1
            if len(rows) < limit:
                rows.append(
                    SheetRow(
                        row_number=header_row + offset,
                        values=row_dict(headers, row),
                    )
                )
        return FindRowsResult(
            found=bool(rows),
            count=len(rows),
            more=matched > len(rows),
            tab=name,
            rows=rows,
        )

    async def _get_row(self, row_number: int, tab: str | None) -> GetRowResult:
        header_row = self.config.header_row
        if row_number <= header_row:
            raise BadArgumentError(
                f"row_number must be below the header row ({header_row})"
            )
        budget = self._budget()
        name = await self._tab(tab, budget)
        header, row = await self.client.read_ranges(
            self.config.spreadsheet_id,
            [
                rows_range(name, header_row, header_row),
                rows_range(name, row_number, row_number),
            ],
            budget=budget,
        )
        headers = header_names(header[0]) if header else []
        cells = row[0] if row else []
        if not headers or not any(c.strip() for c in cells):
            return GetRowResult(found=False, tab=name)
        return GetRowResult(
            found=True,
            tab=name,
            row=SheetRow(row_number=row_number, values=row_dict(headers, cells)),
        )

    async def _append_row(
        self, values: Mapping[str, str], tab: str | None
    ) -> AppendRowResult:
        budget = self._budget()
        name = await self._tab(tab, budget)
        header_row = self.config.header_row
        [header] = await self.client.read_ranges(
            self.config.spreadsheet_id,
            [rows_range(name, header_row, header_row)],
            budget=budget,
        )
        headers = header_names(header[0]) if header else []
        if not headers:
            raise BadArgumentError(
                f"the tab has no column names in row {header_row} to match"
            )
        by_index: dict[int, str] = {}
        unknown: list[str] = []
        for key, cell in values.items():
            index = find_column(headers, key)
            if index is None:
                unknown.append(key)
            else:
                by_index[index] = neutralize_formula(cell)
        if unknown:
            raise BadArgumentError(
                f"unknown column(s): {', '.join(unknown[:10])}; columns are: "
                f"{_column_list(headers)}"
            )
        row = [by_index.get(i, "") for i in range(max(by_index) + 1)]
        if not budget.allows_request():
            raise GoogleApiError("Google is slow right now; please try again")
        table = f"{quote_tab(name)}!A{header_row}:{column_letter(len(headers) - 1)}"
        updated = await self.client.append_row(
            self.config.spreadsheet_id, table, row, budget=budget
        )
        return AppendRowResult(
            appended=True,
            tab=name,
            row_number=updated_row_number(updated),
            message="The row was added.",
        )

    # -- connection test -----------------------------------------------------

    async def describe(self) -> tuple[SpreadsheetInfo, list[str]]:
        """The spreadsheet, plus configured tabs that do not exist in it."""
        info = await self.client.spreadsheet(
            self.config.spreadsheet_id, budget=self._budget()
        )
        configured = [
            *([self.config.default_tab] if self.config.default_tab else []),
            *([self.config.orders_tab] if self.config.orders_tab else []),
            *(self.config.allowed_tabs or []),
        ]
        missing = [
            tab
            for tab in dict.fromkeys(configured)
            if not any(same_tab(tab, real) for real in info.tabs)
        ]
        return info, missing

    # -- helpers -------------------------------------------------------------

    async def _tab(self, requested: str | None, budget: Budget) -> str:
        """The tab a call works on, enforcing ``allowed_tabs``."""
        allowed = self.config.allowed_tabs
        wanted = (requested or "").strip()
        if wanted:
            if allowed is None:
                return wanted
            for tab in allowed:
                if same_tab(tab, wanted):
                    return tab
            raise BadArgumentError(
                f"that tab cannot be used; use one of: {', '.join(allowed)}"
            )
        if self.config.default_tab:
            return self.config.default_tab
        if allowed:
            return allowed[0]
        info = await self.client.spreadsheet(self.config.spreadsheet_id, budget=budget)
        if not info.tabs:
            raise BadArgumentError("the spreadsheet has no tabs")
        if not budget.allows_request():
            raise GoogleApiError("Google is slow right now; please try again")
        return info.tabs[0]

    @staticmethod
    def _unknown_column(column: str, headers: list[str]) -> str:
        if not headers:
            return "the tab has no column names to search"
        return f"there is no column named {column!r}; columns are: " + _column_list(
            headers
        )

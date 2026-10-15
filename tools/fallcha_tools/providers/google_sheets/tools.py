"""MCP tools. Their signatures and docstrings become the agent's functions."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fallcha_tools.core.provider import ConnectionContextFactory
from fallcha_tools.providers.google_common.errors import GoogleToolError
from fallcha_tools.providers.google_sheets.schemas import (
    AccountName,
    AddressOrEircode,
    AppendRowResult,
    Column,
    FindRowsResult,
    GetRowResult,
    MatchMode,
    MatchValue,
    OrderId,
    OrderLookupResult,
    RowNumber,
    RowValues,
    Tab,
)
from fallcha_tools.providers.google_sheets.service import (
    ServiceFactory,
    SheetsService,
)

_READ_ONLY: dict[str, Any] = {"readOnlyHint": True, "openWorldHint": True}
_WRITES: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}


async def _guard[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except GoogleToolError as exc:
        # Only ToolError messages reach the client (mask_error_details).
        raise ToolError(str(exc)) from None


def register_sheets_tools(
    mcp: FastMCP[Any],
    ctx_factory: ConnectionContextFactory,
    service_for: ServiceFactory,
) -> None:
    async def service() -> SheetsService:
        ctx = await ctx_factory()
        try:
            return service_for(ctx)
        except GoogleToolError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(annotations=_READ_ONLY, title="Find rows by a column value")
    async def find_rows(
        column: Column,
        value: MatchValue,
        tab: Tab = None,
        match: MatchMode = "exact",
    ) -> FindRowsResult:
        """Look up rows in the connected Google Sheet where a column matches a
        value, e.g. a caller's phone number or booking reference. Returns each
        matching row as column name -> value. If "found" is false, nothing
        matched; never guess the row's contents."""
        svc = await service()
        return await _guard(svc.find_rows(column, value, tab, match))

    @mcp.tool(annotations=_READ_ONLY, title="Read a row by number")
    async def get_row(row_number: RowNumber, tab: Tab = None) -> GetRowResult:
        """Read one row of the connected Google Sheet by its row number (as
        returned by find_rows)."""
        svc = await service()
        return await _guard(svc.get_row(row_number, tab))

    @mcp.tool(annotations=_WRITES, title="Add a row")
    async def append_row(values: RowValues, tab: Tab = None) -> AppendRowResult:
        """Add a new row to the connected Google Sheet, e.g. to record a lead or
        a message. Give values by column name; only columns in the sheet's
        header row are accepted. Call it once per row: it is not safe to
        repeat."""
        svc = await service()
        return await _guard(svc.append_row(values, tab))

    @mcp.tool(
        annotations=_READ_ONLY, title="Look up a verified caller's order (read-only)"
    )
    async def look_up_order(
        caller_name: AccountName,
        address_or_eircode: AddressOrEircode,
        order_id: OrderId = None,
    ) -> OrderLookupResult:
        """Use when a caller asks about an existing order or account: where their
        adapter is, when their number ports, order status, what package they are
        on. Requires BOTH the name on the account and their Eircode or address;
        ask for both before calling. Read-only: it can never change an order.
        If "verified" is false, read the "say" field and never reveal which
        detail did not match."""
        svc = await service()
        return await _guard(
            svc.look_up_order(caller_name, address_or_eircode, order_id)
        )

"""Typed wrapper over the Google Sheets v4 REST API (values + metadata)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from fallcha_tools.providers.google_common.errors import BadArgumentError
from fallcha_tools.providers.google_common.http import (
    Budget,
    GoogleHttp,
    path_segment,
)
from fallcha_tools.providers.google_common.scopes import SHEETS_API, SHEETS_SCOPE

SPREADSHEET = "spreadsheet"
# One scope for every call: a service-account token minted for it is cached
# and reused across reads and appends.
_SCOPES = (SHEETS_SCOPE,)
TAB_NOT_FOUND = "that tab was not found in the spreadsheet"


@dataclass(frozen=True, slots=True)
class SpreadsheetInfo:
    title: str
    tabs: tuple[str, ...]


def _cells(raw: Any) -> list[list[str]]:
    rows = raw if isinstance(raw, list) else []
    return [[str(cell) for cell in row] for row in rows if isinstance(row, list)]


@dataclass(frozen=True, slots=True)
class SheetsClient(GoogleHttp):
    """Sheets calls as one connection. Every call takes the tool call's
    :class:`Budget`."""

    async def spreadsheet(
        self, spreadsheet_id: str, *, budget: Budget
    ) -> SpreadsheetInfo:
        body = await self._json(
            "GET",
            f"{SHEETS_API}/{path_segment(spreadsheet_id)}",
            _SCOPES,
            SPREADSHEET,
            params={"fields": "properties.title,sheets.properties.title"},
            budget=budget,
        )
        tabs = tuple(
            str(title)
            for sheet in body.get("sheets") or []
            if isinstance(sheet, dict)
            and (title := (sheet.get("properties") or {}).get("title"))
        )
        title = str((body.get("properties") or {}).get("title") or spreadsheet_id)
        return SpreadsheetInfo(title=title, tabs=tabs)

    async def read_ranges(
        self, spreadsheet_id: str, ranges: Sequence[str], *, budget: Budget
    ) -> list[list[list[str]]]:
        """Cell text (as formatted in the sheet) of each A1 range, in order."""
        response = await self._send(
            "GET",
            f"{SHEETS_API}/{path_segment(spreadsheet_id)}/values:batchGet",
            _SCOPES,
            params={"ranges": list(ranges), "majorDimension": "ROWS"},
            budget=budget,
        )
        self._raise_for_range(response)
        value_ranges = self._body(response).get("valueRanges") or []
        found = [
            _cells(item.get("values")) if isinstance(item, dict) else []
            for item in value_ranges
        ]
        return found + [[] for _ in range(len(ranges) - len(found))]

    async def append_row(
        self,
        spreadsheet_id: str,
        table_range: str,
        row: Sequence[str],
        *,
        budget: Budget,
    ) -> str:
        """Append ``row`` after the table at ``table_range``; returns the
        A1 range Google wrote. Values are RAW: stored as typed, never parsed
        as formulas, numbers or dates."""
        response = await self._send(
            "POST",
            f"{SHEETS_API}/{path_segment(spreadsheet_id)}/values/"
            f"{path_segment(table_range)}:append",
            _SCOPES,
            params={
                "valueInputOption": "RAW",
                "insertDataOption": "INSERT_ROWS",
                "includeValuesInResponse": "false",
            },
            json={"majorDimension": "ROWS", "values": [list(row)]},
            budget=budget,
        )
        self._raise_for_range(response)
        updates = self._body(response).get("updates") or {}
        return str(updates.get("updatedRange") or "")

    def _raise_for_range(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 400:
            # Our ranges are well-formed, so a 400 means an unknown tab.
            raise BadArgumentError(TAB_NOT_FOUND)
        raise self._error(response, SPREADSHEET)

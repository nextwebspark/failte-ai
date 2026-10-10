"""A respx-backed fake of the Google Sheets v4 API (metadata, batchGet, append)."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote

import httpx
import respx

from fallcha_tools.providers.google_common.credentials import GOOGLE_TOKEN_URL
from fallcha_tools.providers.google_common.scopes import SHEETS_API

SPREADSHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
ORDERS: list[list[str]] = [
    ["order_id", "customer_name", "address", "eircode", "package", "status", "eta"],
    [
        "VT-1",
        "Jane Murphy",
        "12 Main Street, Galway",
        "H91 X2Y3",
        "Home Fibre",
        "Shipped",
        "Arrives Thursday",
    ],
    [
        "VT-2",
        "John Byrne",
        "Rose Cottage, Kinsale",
        "P17 AB12",
        "Mobile",
        "Pending",
        "",
    ],
]
_ROWS = re.compile(r"^'((?:[^']|'')*)'!(?:A)?(\d+):(?:[A-Z]+)?(\d+)$")
_TABLE = re.compile(r"^'((?:[^']|'')*)'!A(\d+):([A-Z]+)$")


def _tab(quoted: str) -> str:
    return quoted.replace("''", "'")


class FakeSheets:
    def __init__(self, router: respx.MockRouter) -> None:
        self.tabs: dict[str, list[list[str]]] = {
            "Leads": [
                ["Name", "Phone", "Status", "Notes"],
                ["Mary Byrne", "+353 87 111 2222", "New", "wants a quote"],
                ["John Walsh", "+353 86 333 4444", "Won", ""],
                ["mary byrne", "+353 85 555 6666", "Lost", "duplicate?"],
            ],
            "Private": [["Secret"], ["do not read"]],
            "My 'Quoted' Tab": [["Key"], ["v"]],
            "Orders": [list(row) for row in ORDERS],
        }
        self.title = "CRM"
        self.appended: list[dict[str, Any]] = []
        self.batch_ranges: list[list[str]] = []
        self.append_status = 200
        self.token = router.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "ya29.sheets", "expires_in": 3599}
            )
        )
        base = f"{SHEETS_API}/{SPREADSHEET_ID}"
        self.meta = router.get(url__regex=rf"^{re.escape(base)}(\?.*)?$").mock(
            side_effect=self._meta
        )
        self.batch = router.get(
            url__regex=rf"^{re.escape(base)}/values:batchGet\?"
        ).mock(side_effect=self._batch_get)
        self.append = router.post(
            url__regex=rf"^{re.escape(base)}/values/[^/]+:append"
        ).mock(side_effect=self._append)

    def _meta(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {"title": self.title},
                "sheets": [{"properties": {"title": t}} for t in self.tabs],
            },
        )

    def _batch_get(self, request: httpx.Request) -> httpx.Response:
        ranges = request.url.params.get_list("ranges")
        self.batch_ranges.append(ranges)
        value_ranges = []
        for a1 in ranges:
            found = _ROWS.fullmatch(a1)
            if found is None or _tab(found.group(1)) not in self.tabs:
                return httpx.Response(
                    400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT"}}
                )
            rows = self.tabs[_tab(found.group(1))]
            first, last = int(found.group(2)), int(found.group(3))
            chunk = rows[first - 1 : last]
            value_ranges.append(
                {"range": a1, "values": chunk} if chunk else {"range": a1}
            )
        return httpx.Response(200, json={"valueRanges": value_ranges})

    def _append(self, request: httpx.Request) -> httpx.Response:
        if self.append_status != 200:
            return httpx.Response(self.append_status, json={"error": {"code": 500}})
        encoded = request.url.raw_path.decode().split("/values/", 1)[1]
        a1 = unquote(encoded.split(":append", 1)[0])
        found = _TABLE.fullmatch(a1)
        assert found is not None, a1
        tab = _tab(found.group(1))
        body = json.loads(request.content)
        self.appended.append(
            {"tab": tab, "params": dict(request.url.params), "body": body, "a1": a1}
        )
        self.tabs[tab].append(body["values"][0])
        row = len(self.tabs[tab])
        return httpx.Response(
            200,
            json={"updates": {"updatedRange": f"'{tab}'!A{row}:D{row}"}},
        )


def sheets_config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"spreadsheet_id": SPREADSHEET_ID}
    config.update(overrides)
    return config

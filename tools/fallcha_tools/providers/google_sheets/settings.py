"""Per-connection settings of the Google Sheets provider."""

from __future__ import annotations

import re
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHEET_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")

TabName = Annotated[str, Field(min_length=1, max_length=100)]


def same_tab(a: str, b: str) -> bool:
    """Tab names compare case-insensitively, ignoring outer whitespace."""
    return a.strip().casefold() == b.strip().casefold()


class OrderColumns(BaseModel):
    """Header names of the orders tab's columns used by look_up_order.

    Defaults are the original calendar shim's sheet headers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str = Field(default="order_id", min_length=1, max_length=100)
    customer_name: str = Field(default="customer_name", min_length=1, max_length=100)
    address: str = Field(default="address", min_length=1, max_length=100)
    eircode: str = Field(default="eircode", min_length=1, max_length=100)
    package: str = Field(default="package", min_length=1, max_length=100)
    status: str = Field(default="status", min_length=1, max_length=100)
    eta: str = Field(default="eta", min_length=1, max_length=100)
    hardware: str = Field(default="hardware", min_length=1, max_length=100)
    order_date: str = Field(default="order_date", min_length=1, max_length=100)
    monthly_price: str = Field(default="monthly_price", min_length=1, max_length=100)


class SheetsConfig(BaseModel):
    """Which spreadsheet a connection works on, and what tools may touch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    spreadsheet_id: str = Field(
        min_length=10,
        max_length=300,
        description="The spreadsheet's id (or its full docs.google.com URL).",
    )
    default_tab: TabName | None = Field(
        default=None,
        description="Tab used when a tool call names none. Unset: the first "
        "allowed tab, or else the spreadsheet's first tab.",
    )
    allowed_tabs: list[TabName] | None = Field(
        default=None,
        max_length=50,
        description="If set, tools may only read and write these tabs.",
    )
    max_rows_returned: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Most rows find_rows returns in one call.",
    )
    header_row: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Row holding the column names; data starts below it.",
    )

    orders_tab: TabName | None = Field(
        default=None,
        description="Tab holding orders, for the verified look_up_order tool "
        "(caller name + address/Eircode). Unset: order lookup is off.",
    )
    generic_tools_read_orders: bool = Field(
        default=False,
        description="Let find_rows, get_row and append_row use the orders tab "
        "too. Off: the orders tab is reachable only through the verified "
        "look_up_order.",
    )
    order_columns: OrderColumns = Field(
        default_factory=OrderColumns,
        description="Header names of the orders tab's columns.",
    )

    @field_validator("spreadsheet_id")
    @classmethod
    def _sheet_id(cls, value: str) -> str:
        value = value.strip()
        found = _SHEET_URL.search(value)
        if found:
            value = found.group(1)
        if not _SHEET_ID.fullmatch(value):
            raise ValueError("is not a Google Sheets spreadsheet id or URL")
        return value

    @field_validator("default_tab", "orders_tab")
    @classmethod
    def _strip_tab(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("allowed_tabs")
    @classmethod
    def _unique_tabs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unique: list[str] = []
        for tab in (t.strip() for t in value):
            if tab and not any(same_tab(tab, seen) for seen in unique):
                unique.append(tab)
        return unique or None

    @model_validator(mode="after")
    def _default_is_allowed(self) -> Self:
        if (
            self.default_tab is not None
            and self.allowed_tabs is not None
            and not any(same_tab(self.default_tab, t) for t in self.allowed_tabs)
        ):
            raise ValueError("default_tab must be one of allowed_tabs")
        return self

    def is_orders_tab(self, tab: str) -> bool:
        return self.orders_tab is not None and same_tab(tab, self.orders_tab)

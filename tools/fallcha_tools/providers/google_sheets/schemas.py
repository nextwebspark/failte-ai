"""Tool arguments and results. Field descriptions become the agent's docs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Tab = Annotated[
    str | None,
    Field(
        default=None,
        max_length=100,
        description="Tab (worksheet) name. Leave empty to use the default tab.",
    ),
]
Column = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        description="Column name exactly as in the header row (case does not "
        "matter), e.g. 'Phone'.",
    ),
]
MatchValue = Annotated[
    str,
    Field(
        min_length=1,
        max_length=500,
        description="The value to look for in that column.",
    ),
]
MatchMode = Annotated[
    Literal["exact", "contains"],
    Field(
        default="exact",
        description="'exact': the whole cell equals the value (case and extra "
        "spaces ignored). 'contains': the cell contains the value.",
    ),
]
RowNumber = Annotated[
    int,
    Field(
        ge=1,
        le=10_000_000,
        description="Row number as shown in the sheet (from a find_rows result).",
    ),
]
RowValues = Annotated[
    dict[
        Annotated[str, Field(min_length=1, max_length=100)],
        Annotated[str, Field(max_length=5000)],
    ],
    Field(
        min_length=1,
        max_length=100,
        description="Column name -> value for the new row, e.g. "
        "{'Name': 'Mary Byrne', 'Phone': '+353 87 123 4567'}. Columns must "
        "exist in the header row; leave out columns you have no value for.",
    ),
]


# -- order lookup (ported from the calendar shim; same contract) ------------

AccountName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        description=(
            "The name on the account, as the caller said it. A surname on its "
            "own is fine."
        ),
    ),
]
AddressOrEircode = Annotated[
    str,
    Field(
        min_length=1,
        max_length=300,
        description=(
            "Their Eircode if they gave one, otherwise their address, as spoken. "
            "Pass it through verbatim; do not tidy it up or invent missing parts."
        ),
    ),
]
OrderId = Annotated[
    str | None,
    Field(
        max_length=64,
        description=(
            "Order reference like VT-10412, only if the caller read one out. "
            "Leave empty otherwise."
        ),
    ),
]


class OrderLookupResult(BaseModel):
    verified: bool
    order_id: str | None = None
    customer_name: str | None = None
    package: str | None = None
    hardware: str | None = None
    status: str | None = None
    eta: str | None = None
    order_date: str | None = None
    monthly_price: str | None = None
    say: str = Field(description="Read this to the caller word for word.")


class OrderLookupRequest(BaseModel):
    caller_name: AccountName
    address_or_eircode: AddressOrEircode
    order_id: OrderId = None


# -- generic rows ----------------------------------------------------------


class SheetRow(BaseModel):
    row_number: int = Field(description="Row number in the sheet.")
    values: dict[str, str] = Field(description="Column name -> cell text.")


class FindRowsResult(BaseModel):
    found: bool
    count: int = Field(description="Rows returned.")
    more: bool = Field(
        description="True if more rows matched than were returned; narrow the "
        "search to see them."
    )
    tab: str
    rows: list[SheetRow]


class GetRowResult(BaseModel):
    found: bool
    tab: str
    row: SheetRow | None = None


class AppendRowResult(BaseModel):
    appended: bool
    tab: str
    row_number: int | None = Field(
        default=None, description="Where the row was written, if Google said."
    )
    message: str

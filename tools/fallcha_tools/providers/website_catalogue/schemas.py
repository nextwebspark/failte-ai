"""Tool arguments and results; the shapes of the original product service."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

Query = Annotated[
    str,
    Field(
        min_length=1,
        max_length=300,
        description=(
            "What the caller is looking for, in their own words: 'a lifejacket "
            "for a child', 'crewsaver rescue system', 'something to clean the "
            "hull'. Pass what they said, do not translate it into a catalogue "
            "name."
        ),
    ),
]
MaxResults = Annotated[
    int | None,
    Field(
        default=None,
        ge=1,
        le=100,
        description="How many products to name (at most 5 are ever named).",
    ),
]
Sku = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        description="The exact sku string copied from a search_products result. "
        "Never make this up.",
    ),
]


class ProductSummary(BaseModel):
    sku: str
    name: str
    brand: str
    category: str
    price: float | None
    currency: str
    price_spoken: str
    in_stock: bool
    url: str


class SearchResult(BaseModel):
    found: bool
    count: int
    products: list[ProductSummary]
    unmatched_terms: list[str] | None = Field(
        default=None,
        description="Words of the query found nowhere in the catalogue.",
    )
    say: str = Field(description="Read this to the caller word for word.")


class DetailResult(BaseModel):
    found: bool
    sku: str | None = None
    name: str | None = None
    brand: str | None = None
    category: str | None = None
    price: float | None = None
    price_spoken: str | None = None
    in_stock: bool | None = None
    description: str | None = None
    url: str | None = None
    say: str = Field(description="Read this to the caller word for word.")


class SearchRequest(BaseModel):
    query: Query
    max_results: MaxResults = None


class DetailRequest(BaseModel):
    sku: Sku

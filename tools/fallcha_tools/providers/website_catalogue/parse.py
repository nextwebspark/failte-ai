"""Product data from a page's schema.org JSON-LD (ported from ``ingest.py``).

Every product page of a typical shop publishes Product JSON-LD (name, sku,
brand, price, availability, description) plus a BreadcrumbList giving its
category. That structured data is what gets indexed; page text is ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

_SPACES = re.compile(r"\s+")
MAX_SKU = 200
MAX_NAME = 500
MAX_TEXT = 300
MAX_DESCRIPTION = 5000
MAX_URL = 2000


@dataclass(frozen=True, slots=True)
class ParsedProduct:
    sku: str
    name: str
    brand: str
    category: str
    description: str
    price: Decimal | None
    currency: str
    availability: str
    url: str


class _JsonLdScripts(HTMLParser):
    """Collects the text of every ``<script type="application/ld+json">``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._inside = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            kind = (dict(attrs).get("type") or "").split(";")[0].strip().lower()
            self._inside = kind == "application/ld+json"
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside:
            self.blocks.append("".join(self._parts))
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self._parts.append(data)


def _types(node: dict[str, Any]) -> set[str]:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return {str(k).rsplit("/", 1)[-1] for k in kinds if k}


def json_ld_blocks(html: str) -> list[dict[str, Any]]:
    parser = _JsonLdScripts()
    try:
        parser.feed(html)
        parser.close()
    except (AssertionError, ValueError):  # malformed markup
        pass
    blocks: list[dict[str, Any]] = []
    for text in parser.blocks:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        # A page may ship a single object, an array, or an @graph.
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                blocks.extend(g for g in graph if isinstance(g, dict))
            else:
                blocks.append(item)
    return blocks


def _category_from_breadcrumb(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if "BreadcrumbList" not in _types(block):
            continue
        names = []
        elements = block.get("itemListElement")
        for item in elements if isinstance(elements, list) else []:
            if not isinstance(item, dict):
                continue
            node = item.get("item")
            name = node.get("name") if isinstance(node, dict) else item.get("name")
            if name:
                names.append(str(name))
        # Drop "Home" and the leaf (the product itself); what is left is the
        # category path a caller might describe: "Safety > Lifejackets".
        trail = [n for n in names if n.lower() != "home"][:-1]
        if trail:
            return " > ".join(trail)
    return ""


def _text(value: Any, limit: int) -> str:
    return _SPACES.sub(" ", str(value or "")).strip()[:limit]


def _price(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        price = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None
    if not price.is_finite() or price < 0 or price >= Decimal("1e12"):
        return None
    return price.quantize(Decimal("0.01"))


def parse_product(html: str, url: str, default_currency: str) -> ParsedProduct | None:
    blocks = json_ld_blocks(html)
    product = next((b for b in blocks if "Product" in _types(b)), None)
    if product is None:
        return None
    offers: Any = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    offers = offers if isinstance(offers, dict) else {}

    sku = _text(
        product.get("sku") or product.get("productID") or product.get("mpn"), MAX_SKU
    )
    name = _text(product.get("name"), MAX_NAME)
    if not sku or not name:
        return None
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    price = _price(offers.get("price"))
    if price is None:
        price = _price(offers.get("lowPrice"))  # AggregateOffer
    currency = _text(offers.get("priceCurrency"), 8).upper() or default_currency
    return ParsedProduct(
        sku=sku,
        name=name,
        brand=_text(brand, MAX_TEXT),
        category=_text(_category_from_breadcrumb(blocks), MAX_TEXT),
        description=_text(product.get("description"), MAX_DESCRIPTION),
        price=price,
        currency=currency,
        availability=_text(offers.get("availability"), 200).rsplit("/", 1)[-1][:64],
        url=url[:MAX_URL],
    )

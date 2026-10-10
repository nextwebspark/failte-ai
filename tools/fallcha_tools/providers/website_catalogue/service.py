"""Answers to product questions (ported from the product service's ``app.py``)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fallcha_tools.providers.website_catalogue.schemas import (
    DetailResult,
    ProductSummary,
    SearchResult,
)
from fallcha_tools.providers.website_catalogue.settings import CatalogueConfig
from fallcha_tools.providers.website_catalogue.speech import (
    in_stock,
    spoken_price,
    stock_phrase,
)
from fallcha_tools.providers.website_catalogue.store import (
    CatalogueStore,
    Hit,
    StoredProduct,
    query_terms,
    stem,
)

MAX_RESULTS_CEILING = 5
DETAIL_CHARS = 400
NO_MATCH = (
    "I could not find that one. Could you describe it a different way, or tell "
    "me the brand?"
)
NO_DETAIL = "I do not have the details for that one to hand."


def _describe(p: StoredProduct) -> str:
    return (
        f"the {p.name}, {spoken_price(p.price, p.currency)}, "
        f"{stock_phrase(p.availability)}"
    )


def _summary(p: StoredProduct) -> ProductSummary:
    return ProductSummary(
        sku=p.sku,
        name=p.name,
        brand=p.brand,
        category=p.category,
        price=float(p.price) if p.price is not None else None,
        currency=p.currency,
        price_spoken=spoken_price(p.price, p.currency),
        in_stock=in_stock(p.availability),
        url=p.url,
    )


def keep(hits: list[Hit], usable: list[str], limit: int) -> list[StoredProduct]:
    """Hits worth reading out, best first: the caller's words in the NAME or
    BRAND (these sort first), or a strong description-only match."""
    scored = []
    for hit in hits:
        p = hit.product
        surface = f"{p.name} {p.brand}".lower()
        on_surface = any(stem(t) in surface for t in usable)
        if not on_surface and not hit.near:
            continue
        scored.append((0 if on_surface else 1, -hit.rank, p.sku, p))
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return [p for *_, p in scored[:limit]]


@dataclass(frozen=True, slots=True)
class CatalogueService:
    store: CatalogueStore
    config: CatalogueConfig
    org_id: int
    connection_id: uuid.UUID

    async def search(self, query: str, max_results: int | None) -> SearchResult:
        limit = min(max_results or self.config.max_results, MAX_RESULTS_CEILING)
        hits, unmatched = await self._find(query, limit)
        if not hits:
            # Identical wording for "no match" and "nothing close enough": the
            # caller learns nothing about the index either way.
            offer = self.config.no_match_transfer_offer.strip()
            return SearchResult(
                found=False,
                count=0,
                products=[],
                say=f"{NO_MATCH} {offer}" if offer else NO_MATCH,
            )
        parts = [_describe(p) for p in hits]
        listed = (
            parts[0] if len(parts) == 1 else "; ".join(parts[:-1]) + f"; or {parts[-1]}"
        )
        # If the caller named something we could not match at all (usually a
        # brand we do not stock), say so before offering an alternative.
        say = (
            f"I could not find that exact one, but I do have {listed}."
            if unmatched
            else f"I have {listed}."
        )
        return SearchResult(
            found=True,
            count=len(hits),
            products=[_summary(p) for p in hits],
            unmatched_terms=unmatched,
            say=say,
        )

    async def detail(self, sku: str) -> DetailResult:
        p = await self.store.by_sku(self.org_id, self.connection_id, sku.strip())
        if p is None:
            return DetailResult(found=False, say=NO_DETAIL)
        description = p.description.strip()
        if len(description) > DETAIL_CHARS:
            description = description[:DETAIL_CHARS].rsplit(" ", 1)[0] + "..."
        say = (
            f"The {p.name} is {spoken_price(p.price, p.currency)} and it is "
            f"{stock_phrase(p.availability)}."
        )
        if description:
            say += f" {description}"
        return DetailResult(
            found=True,
            sku=p.sku,
            name=p.name,
            brand=p.brand,
            category=p.category,
            price=float(p.price) if p.price is not None else None,
            price_spoken=spoken_price(p.price, p.currency),
            in_stock=in_stock(p.availability),
            description=description,
            url=p.url,
            say=say,
        )

    async def _find(
        self, spoken: str, limit: int
    ) -> tuple[list[StoredProduct], list[str]]:
        """(products, unmatched words). Offering a Guy Cotten jacket to someone
        who asked for a Musto is fine only if we say we could not find the
        Musto, so both are needed."""
        terms = query_terms(spoken)
        if not terms:
            return [], []
        presence = await self.store.term_presence(
            self.org_id, self.connection_id, terms
        )
        unmatched = [t for t in terms if presence.get(t) is False]
        usable = [t for t in terms if presence.get(t) is True]
        if not usable:
            return [], unmatched
        # AND first, but if everything it returns is too weak to read out,
        # fall through to OR (else "anchors for a small boat" misses real
        # anchors when AND only matched two unrelated descriptions).
        kept: list[StoredProduct] = []
        if len(usable) > 1:
            kept = keep(
                await self.store.candidates(
                    self.org_id, self.connection_id, usable, require_all=True
                ),
                usable,
                limit,
            )
        if not kept:
            kept = keep(
                await self.store.candidates(
                    self.org_id, self.connection_id, usable, require_all=False
                ),
                usable,
                limit,
            )
        return kept, unmatched

"""Postgres catalogue store and search (ported from the SQLite/FTS5 store).

Every query filters on both ``org_id`` and ``connection_id``.

Search keeps the original's answer semantics; precision beats recall:

* the caller's words are lower-cased, split on non-alphanumerics, and
  words of 1-2 letters and spoken filler (``STOPWORDS``) are dropped;
* words that appear nowhere in the catalogue are reported as unmatched
  ("I could not find that exact one, but ...");
* all remaining words must match if that finds anything worth reading out
  (AND), else any of them (OR);
* a hit is read out only if one of the caller's words is in the product's
  name or brand, or if it is a strong description-only match.

Ranking uses ``ts_rank`` with the original bm25 column weights (name 1.0,
brand 0.6, category 0.3, description 0.1). The original's "strong
description match" was a bm25 score threshold; Postgres ranks are not on
that scale (and could not tell the original's own good and bad examples
apart), so a description-only hit is strong when two of the caller's words
appear within three words of each other in it ("cleans the hull" for
"something to clean the hull"; not "anchor ... small" scattered through an
unrelated description).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import combinations
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from fallcha_tools.core.db import Database
from fallcha_tools.providers.website_catalogue.models import CatalogueProduct
from fallcha_tools.providers.website_catalogue.parse import ParsedProduct

# Words that carry no signal in a spoken product request and, worse, match
# half the catalogue ("do you have any rope for a boat" -> "boat" is in most
# descriptions). Dropped before the query reaches the index.
STOPWORDS = {
    "a", "an", "and", "any", "are", "boat", "can", "could", "do", "does", "for",
    "get", "got", "have", "how", "i", "im", "is", "it", "looking", "me", "much",
    "my", "need", "of", "on", "or", "please", "sell", "some", "something",
    "the", "to", "want", "was", "we", "what", "with", "would", "you", "your",
}  # fmt: skip
CANDIDATES = 50
NEAR_DISTANCE = 3
MAX_NEAR_TERMS = 6
UPSERT_BATCH = 100
_WORD = re.compile(r"[a-z0-9]+")
_TABLE = "fallcha_tools.catalogue_products"
_WEIGHTS = "{0.1,0.3,0.6,1.0}"  # D, C, B, A


def query_terms(spoken: str) -> list[str]:
    words = [t for t in _WORD.findall((spoken or "").lower()) if len(t) > 2]
    return list(dict.fromkeys(t for t in words if t not in STOPWORDS))


def stem(word: str) -> str:
    # Crude, deliberately: it only has to agree with what the index's
    # stemmer decided, so "lifejackets" and "lifejacket" collapse together.
    for suffix in ("ies", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def near_query(terms: Sequence[str]) -> str | None:
    """A tsquery matching any two of ``terms`` within NEAR_DISTANCE words."""
    clauses = [
        f"({a} <{d}> {b})"
        for x, y in combinations(terms[:MAX_NEAR_TERMS], 2)
        for a, b in ((x, y), (y, x))
        for d in range(1, NEAR_DISTANCE + 1)
    ]
    return " | ".join(clauses) or None


@dataclass(frozen=True, slots=True)
class StoredProduct:
    sku: str
    name: str
    brand: str
    category: str
    description: str
    price: Decimal | None
    currency: str
    availability: str
    url: str


@dataclass(frozen=True, slots=True)
class Hit:
    product: StoredProduct
    rank: float
    near: bool


def _product(row: Any) -> StoredProduct:
    return StoredProduct(
        sku=row.sku,
        name=row.name,
        brand=row.brand,
        category=row.category,
        description=row.description,
        price=row.price,
        currency=row.currency,
        availability=row.availability,
        url=row.url,
    )


@dataclass(frozen=True)
class CatalogueStore:
    db: Database

    # -- writes (sync) ---------------------------------------------------------

    async def upsert(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        products: Sequence[ParsedProduct],
        fetched_at: datetime,
    ) -> None:
        if not products:
            return
        by_sku = {p.sku: p for p in products}  # last wins within a batch
        rows = [
            {
                "connection_id": connection_id,
                "org_id": org_id,
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "description": p.description,
                "price": p.price,
                "currency": p.currency,
                "availability": p.availability,
                "url": p.url,
                "fetched_at": fetched_at,
            }
            for p in by_sku.values()
        ]
        statement = insert(CatalogueProduct).values(rows)
        updated = {
            column: statement.excluded[column]
            for column in (
                "name",
                "brand",
                "category",
                "description",
                "price",
                "currency",
                "availability",
                "url",
                "fetched_at",
            )
        }
        async with self.db.session() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        CatalogueProduct.connection_id,
                        CatalogueProduct.sku,
                    ],
                    set_=updated,
                    where=CatalogueProduct.org_id == org_id,
                )
            )
            await session.commit()

    async def prune(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        *,
        older_than: datetime,
        keep_urls: Sequence[str],
    ) -> int:
        """Drop products not refreshed by this sync whose page is no longer
        listed in the sitemap (pages that failed to load keep their row)."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(CatalogueProduct)
                .where(
                    CatalogueProduct.org_id == org_id,
                    CatalogueProduct.connection_id == connection_id,
                    CatalogueProduct.fetched_at < older_than,
                    CatalogueProduct.url.not_in(list(keep_urls)),
                )
                .returning(CatalogueProduct.sku)
            )
            removed = len(result.all())
            await session.commit()
        return removed

    async def count(self, org_id: int, connection_id: uuid.UUID) -> int:
        async with self.db.session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(CatalogueProduct)
                .where(
                    CatalogueProduct.org_id == org_id,
                    CatalogueProduct.connection_id == connection_id,
                )
            )
        return int(total or 0)

    # -- reads (tools) ---------------------------------------------------------

    async def by_sku(
        self, org_id: int, connection_id: uuid.UUID, sku: str
    ) -> StoredProduct | None:
        async with self.db.session() as session:
            row = await session.scalar(
                select(CatalogueProduct).where(
                    CatalogueProduct.org_id == org_id,
                    CatalogueProduct.connection_id == connection_id,
                    CatalogueProduct.sku == sku,
                )
            )
        return _product(row) if row is not None else None

    async def term_presence(
        self, org_id: int, connection_id: uuid.UUID, terms: Sequence[str]
    ) -> dict[str, bool | None]:
        """Per term: is it anywhere in the catalogue? None when the index
        ignores the word entirely (a Postgres stopword), so it neither
        matches nor counts as unmatched."""
        if not terms:
            return {}
        async with self.db.session() as session:
            rows = await session.execute(
                text(
                    f"""
                    SELECT t.term,
                           numnode(plainto_tsquery('english', t.term)) = 0
                               AS ignored,
                           EXISTS (
                               SELECT 1 FROM {_TABLE} p
                               WHERE p.org_id = :org_id
                                 AND p.connection_id = :connection_id
                                 AND p.search @@ plainto_tsquery('english', t.term)
                           ) AS present
                    FROM unnest(CAST(:terms AS text[])) AS t(term)
                    """
                ),
                {
                    "org_id": org_id,
                    "connection_id": connection_id,
                    "terms": list(terms),
                },
            )
            return {
                row.term: (None if row.ignored else bool(row.present)) for row in rows
            }

    async def candidates(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        terms: Sequence[str],
        *,
        require_all: bool,
    ) -> list[Hit]:
        """Up to CANDIDATES matching products, best ranked first. ``terms``
        must be ``query_terms`` output (lower-case alphanumerics only)."""
        if not terms or not all(_WORD.fullmatch(t) for t in terms):
            return []
        match = (" & " if require_all else " | ").join(terms)
        near = near_query(terms)
        near_sql = "p.search @@ to_tsquery('english', :near)" if near else "false"
        params: dict[str, Any] = {
            "org_id": org_id,
            "connection_id": connection_id,
            "match": match,
            "limit": CANDIDATES,
        }
        if near:
            params["near"] = near
        async with self.db.session() as session:
            rows = await session.execute(
                text(
                    f"""
                    SELECT p.sku, p.name, p.brand, p.category, p.description,
                           p.price, p.currency, p.availability, p.url,
                           ts_rank('{_WEIGHTS}', p.search, q) AS rank,
                           {near_sql} AS near
                    FROM {_TABLE} p, to_tsquery('english', :match) q
                    WHERE p.org_id = :org_id
                      AND p.connection_id = :connection_id
                      AND p.search @@ q
                    ORDER BY rank DESC, p.sku
                    LIMIT :limit
                    """
                ),
                params,
            )
            return [
                Hit(product=_product(row), rank=float(row.rank), near=bool(row.near))
                for row in rows
            ]

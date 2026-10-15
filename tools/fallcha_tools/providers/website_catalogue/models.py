"""The imported catalogue: one row per product per connection."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fallcha_tools.core.models import Base

# What a caller might describe a product by, weighted like the original
# FTS5 bm25 weights (name 10, brand 6, category 3, description 1) map onto
# Postgres's four weight classes A > B > C > D. The ``english`` config stems
# like the original porter tokenizer ("lifejackets" finds "Lifejacket").
SEARCH_CONFIG = "english"
SEARCH_EXPRESSION = (
    "setweight(to_tsvector('english'::regconfig, coalesce(name, '')), 'A') || "
    "setweight(to_tsvector('english'::regconfig, coalesce(brand, '')), 'B') || "
    "setweight(to_tsvector('english'::regconfig, coalesce(category, '')), 'C') || "
    "setweight(to_tsvector('english'::regconfig, coalesce(description, '')), 'D')"
)


class CatalogueProduct(Base):
    __tablename__ = "catalogue_products"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sku: Mapped[str] = mapped_column(String(200), primary_key=True)
    # Redundant with the connection, but every query filters on it too, so a
    # bug in one filter can never leak another workspace's catalogue.
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    availability: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=""
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_EXPRESSION, persisted=True), nullable=True
    )

    __table_args__ = (
        Index(None, "org_id", "connection_id"),
        Index(None, "search", postgresql_using="gin"),
    )

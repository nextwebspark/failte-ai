"""How an owner arranged their report: which cards are on, in what order,
which go in the email, and their own average value for the money estimate.

Saved per business as the ``REPORT_LAYOUT`` organization configuration row
(no table of its own), one entry per pack, so an owner and their staff see
the same report. A pack never saved reads as its defaults. Cards added to a
pack later appear at the end, with their defaults; cards a pack no longer
has are dropped.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from api.enums import OrganizationConfigurationKey
from api.services.report_cards.catalogue import PackSpec

LAYOUT_KEY = OrganizationConfigurationKey.REPORT_LAYOUT.value

# The most an owner may enter as an average (per cover, appointment, job).
MAX_AVERAGE = Decimal("100000")


class CardChoice(BaseModel):
    key: str
    on: bool = True
    email: bool = False


class PackLayout(BaseModel):
    cards: list[CardChoice] = Field(default_factory=list)
    updated_at: datetime | None = None
    updated_by: str | None = None


class StoredLayout(BaseModel):
    packs: dict[str, PackLayout] = Field(default_factory=dict)
    # The owner's own average per pack ("restaurant": 35), in euro.
    averages: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("averages")
    @classmethod
    def _positive(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        return {k: v for k, v in value.items() if Decimal(0) < v <= MAX_AVERAGE}


def parse_layout(value: Any, organization_id: int | None = None) -> StoredLayout:
    if not isinstance(value, dict) or not value:
        return StoredLayout()
    try:
        return StoredLayout.model_validate(value)
    except ValidationError as exc:
        logger.warning(
            f"Unreadable report layout for organization {organization_id}: "
            f"{exc.error_count()} error(s). Using the pack's defaults."
        )
        return StoredLayout()


def default_cards(pack: PackSpec) -> list[CardChoice]:
    return [CardChoice(key=c.key, on=True, email=c.email) for c in pack.cards]


def effective_cards(pack: PackSpec, stored: StoredLayout) -> list[CardChoice]:
    """The pack's cards in the owner's order and choices: the saved ones
    still in the pack, then any the pack has gained, with their defaults."""
    saved = stored.packs.get(pack.pack.value)
    if saved is None:
        return default_cards(pack)
    known = set(pack.keys)
    seen: set[str] = set()
    cards: list[CardChoice] = []
    for choice in saved.cards:
        if choice.key in known and choice.key not in seen:
            cards.append(choice)
            seen.add(choice.key)
    cards += [c for c in default_cards(pack) if c.key not in seen]
    return cards


def average(pack: PackSpec, stored: StoredLayout) -> Decimal | None:
    if pack.value_unit is None:
        return None
    return stored.averages.get(pack.pack.value)


class LayoutError(ValueError):
    pass


def save_pack(
    stored: StoredLayout,
    pack: PackSpec,
    cards: list[CardChoice],
    average_value: Decimal | None,
    *,
    by: str | None,
    now: datetime,
) -> StoredLayout:
    """The layout with *pack* saved as given. Every card must be one of the
    pack's, each once; any the owner didn't send keep their place at the
    end. Mutates and returns *stored*."""
    known = set(pack.keys)
    keys = [c.key for c in cards]
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise LayoutError(f"Not a card in this report: {', '.join(unknown)}")
    if len(set(keys)) != len(keys):
        raise LayoutError("Each card can only be listed once.")
    if average_value is not None:
        if pack.value_unit is None:
            raise LayoutError("This report has no money estimate.")
        if not Decimal(0) < average_value <= MAX_AVERAGE:
            raise LayoutError("Enter an average between €0 and €100,000.")
    missing = [c for c in default_cards(pack) if c.key not in set(keys)]
    stored.packs[pack.pack.value] = PackLayout(
        cards=[*cards, *missing], updated_at=now, updated_by=by
    )
    if pack.value_unit is not None:
        if average_value is None:
            stored.averages.pop(pack.pack.value, None)
        else:
            stored.averages[pack.pack.value] = average_value.quantize(Decimal("0.01"))
    return stored


def reset_pack(stored: StoredLayout, pack: PackSpec) -> StoredLayout:
    """Back to the pack's own cards. The owner's average stays: it is a
    fact about their business, not a layout choice."""
    stored.packs.pop(pack.pack.value, None)
    return stored

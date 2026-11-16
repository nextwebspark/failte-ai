"""Which Home cards show, and which come first.

A layout names the cards that are hidden and the cards pinned to the top (in
pin order). Every other card shows in its usual place, so a card added to
Home later shows until someone hides it.

Layouts are saved at three levels, and the first one found wins whole (they
are not merged):

    person     the member's own layout, saved on their account so it follows
               them to every device (``user_configurations`` HOME_LAYOUT)
    workspace  the default an admin saved for the business
               (``organization_configurations`` HOME_LAYOUT)
    platform   the default a platform admin saved for every workspace without
               its own (``platform_settings`` "home_layout")
    default    BUILT_IN_LAYOUT below

Nothing here invents a number: a layout only decides which cards are drawn.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from api.db import db_client
from api.enums import OrganizationConfigurationKey, UserConfigurationKey

PERSON_KEY = UserConfigurationKey.HOME_LAYOUT.value
WORKSPACE_KEY = OrganizationConfigurationKey.HOME_LAYOUT.value
PLATFORM_KEY = "home_layout"

LayoutSource = Literal["person", "workspace", "platform", "default"]

# A card id as Home uses it ("recent-calls"). Ids Home doesn't know (yet) are
# kept, so a layout saved by a newer app still reads in an older one.
_CARD_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_MAX_CARDS = 30


class HomeCard(BaseModel):
    id: str
    label: str


# The cards Home has today, in their usual order. The UI draws them; this list
# gives the platform admin page their names.
HOME_CARDS: tuple[HomeCard, ...] = (
    HomeCard(id="get-started", label="Get started (before the first call)"),
    HomeCard(id="tiles", label="Call numbers (calls, handled, call backs, passed on)"),
    HomeCard(id="attention", label="Needs your attention"),
    HomeCard(id="callers-wanted", label="What callers wanted"),
    HomeCard(id="when-called", label="When people called"),
    HomeCard(id="recent-calls", label="Recent calls"),
    HomeCard(id="your-agent", label="Your agent"),
    HomeCard(id="quick-links", label="Quick links"),
)


class HomeLayout(BaseModel):
    hidden: list[str] = Field(default_factory=list)
    pinned: list[str] = Field(default_factory=list)

    @field_validator("hidden", "pinned")
    @classmethod
    def _card_ids(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for card in value:
            if not isinstance(card, str) or not _CARD_ID.match(card):
                raise ValueError(f"Not a card: {card!r}")
            if card not in seen:
                seen.append(card)
        if len(seen) > _MAX_CARDS:
            raise ValueError(f"At most {_MAX_CARDS} cards")
        return seen


# Every card shows until someone chooses otherwise: existing workspaces see
# Home as they always have. A platform admin can give workspaces without
# their own default a calmer first visit (the "Calm first visit" preset on
# the platform admin's Home layout page).
BUILT_IN_LAYOUT = HomeLayout(hidden=[], pinned=[])


def parse_layout(value: Any, where: str) -> HomeLayout | None:
    """A stored layout, or None when there is none or it no longer reads."""
    if not isinstance(value, dict) or not value:
        return None
    try:
        return HomeLayout.model_validate(value)
    except ValidationError as exc:
        logger.warning(
            f"Unreadable Home layout ({where}): {exc.error_count()} error(s); ignored"
        )
        return None


def resolve_layout(
    person: HomeLayout | None,
    workspace: HomeLayout | None,
    platform: HomeLayout | None,
) -> tuple[HomeLayout, LayoutSource]:
    """The first layout saved, person first; the built-in one otherwise."""
    if person is not None:
        return person, "person"
    if workspace is not None:
        return workspace, "workspace"
    if platform is not None:
        return platform, "platform"
    return BUILT_IN_LAYOUT, "default"


def _dump(layout: HomeLayout) -> dict[str, Any]:
    return layout.model_dump(mode="json")


async def person_layout(user_id: int) -> HomeLayout | None:
    value = await db_client.get_user_configuration_value(user_id, PERSON_KEY)
    return parse_layout(value, f"user {user_id}")


async def workspace_layout(organization_id: int) -> HomeLayout | None:
    value = await db_client.get_configuration_value(organization_id, WORKSPACE_KEY)
    return parse_layout(value, f"organization {organization_id}")


async def platform_layout() -> HomeLayout | None:
    value = await db_client.get_platform_setting(PLATFORM_KEY)
    return parse_layout(value, "platform")


async def save_person_layout(user_id: int, layout: HomeLayout) -> None:
    await db_client.upsert_user_configuration_value(user_id, PERSON_KEY, _dump(layout))


async def clear_person_layout(user_id: int) -> None:
    await db_client.delete_user_configuration_value(user_id, PERSON_KEY)


async def save_workspace_layout(organization_id: int, layout: HomeLayout) -> None:
    await db_client.upsert_configuration(organization_id, WORKSPACE_KEY, _dump(layout))


async def clear_workspace_layout(organization_id: int) -> None:
    await db_client.delete_configuration(organization_id, WORKSPACE_KEY)


async def save_platform_layout(
    layout: HomeLayout | None, *, actor_user_id: int, action: str
) -> None:
    await db_client.set_platform_setting(
        key=PLATFORM_KEY,
        value=_dump(layout) if layout is not None else None,
        actor_user_id=actor_user_id,
        action=action,
    )

"""Thumbs up/down on help answers, kept as metadata only: which answer, which
guide sections it used, which screen, up or down. Never the question or the
answer text, so it fits the privacy rules without a retention policy of its
own. It shows which guide sections need work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.services.help_assistant.knowledge import load_chunks, normalise_page

FEEDBACK_KEY = OrganizationConfigurationKey.HELP_FEEDBACK.value
MAX_STORED = 300


class HelpFeedbackIn(BaseModel):
    answer_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    helpful: bool
    kind: Literal["answer", "not_covered", "off_topic", "unavailable"] = "answer"
    sources: list[str] = Field(default_factory=list, max_length=10)
    page: str | None = Field(default=None, max_length=300)

    @field_validator("sources")
    @classmethod
    def _known_sources(cls, value: list[str]) -> list[str]:
        known = {chunk.id for chunk in load_chunks()}
        return [source for source in value if source in known]


async def record_feedback(
    organization_id: int, body: HelpFeedbackIn, now: datetime | None = None
) -> None:
    row = await db_client.get_configuration(organization_id, FEEDBACK_KEY)
    value = row.value if row is not None else None
    items = value.get("feedback") if isinstance(value, dict) else None
    items = [
        item
        for item in (items if isinstance(items, list) else [])
        # A second vote on the same answer replaces the first.
        if isinstance(item, dict) and item.get("answer_id") != body.answer_id
    ]
    items.append(
        {
            "answer_id": body.answer_id,
            "helpful": body.helpful,
            "kind": body.kind,
            "sources": body.sources,
            "page": normalise_page(body.page),
            "at": (now or datetime.now(UTC)).isoformat(),
        }
    )
    await db_client.upsert_configuration(
        organization_id, FEEDBACK_KEY, {"feedback": items[-MAX_STORED:]}
    )

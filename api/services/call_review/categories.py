"""What callers wanted, in each kind of business's own words.

Every starter template has its own set of reasons (a restaurant's
"Reservations", a clinic's "Appointments"), always ending in "Other". A run
is reviewed against the set of the template its agent started from; agents
built any other way use the general set.

Which template an agent started from: the ``template_category`` stored in
its business facts when it was made from a starter, else the starter whose
opening instructions its steps still carry, else general.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# The business fact a starter stamps on the agent it creates.
TEMPLATE_CATEGORY_FACT = "template_category"

OTHER = "other"


@dataclass(frozen=True, slots=True)
class Reason:
    key: str
    label: str
    # What belongs here, for the reviewer.
    hint: str


@dataclass(frozen=True, slots=True)
class ReasonSet:
    # The starter template category (``StarterTemplate.category``).
    template: str
    # What the business is, for the reviewer: "a restaurant".
    business: str
    reasons: tuple[Reason, ...]
    # The donut's "bookings taken" chip, worded for the business; None when
    # this kind of agent doesn't book on a calendar.
    bookings_label: str | None

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(r.key for r in self.reasons)

    def label(self, key: str) -> str:
        for reason in self.reasons:
            if reason.key == key:
                return reason.label
        return self.label(OTHER)


_OTHER = Reason(OTHER, "Other", "anything else, wrong numbers, sales calls")

RESTAURANT = ReasonSet(
    template="restaurant",
    business="a restaurant",
    reasons=(
        Reason("reservations", "Reservations", "book a table"),
        Reason(
            "questions",
            "Questions (hours, menu, parking)",
            "opening hours, menu, allergies, parking, directions, prices",
        ),
        Reason(
            "changes",
            "Changes & cancellations",
            "change, move or cancel an existing booking",
        ),
        Reason("takeaway", "Takeaway orders", "order food to collect or deliver"),
        _OTHER,
    ),
    bookings_label="bookings taken",
)

CLINIC = ReasonSet(
    template="clinic",
    business="a clinic",
    reasons=(
        Reason("appointments", "Appointments", "book a new appointment"),
        Reason("questions", "Questions", "hours, prices, insurance, directions"),
        Reason(
            "changes",
            "Changes & cancellations",
            "move or cancel an existing appointment",
        ),
        Reason(
            "urgent",
            "Urgent",
            "pain, an emergency or wanting to be seen today",
        ),
        _OTHER,
    ),
    bookings_label="appointments booked",
)

SALON = ReasonSet(
    template="salon",
    business="a salon or barbers",
    reasons=(
        Reason("appointments", "Appointments", "book a cut, colour or treatment"),
        Reason(
            "questions",
            "Questions (prices, services)",
            "prices, services, stylists, hours, parking",
        ),
        Reason(
            "changes",
            "Changes & cancellations",
            "move or cancel an existing appointment",
        ),
        Reason("walk_ins", "Walk-ins & wait times", "walk-ins, how long the wait is"),
        _OTHER,
    ),
    bookings_label="appointments booked",
)

TRADES = ReasonSet(
    template="trades",
    business="a trades business (plumbing, electrics, repairs)",
    reasons=(
        Reason("new_job", "New jobs & quotes", "a new job, a quote or an estimate"),
        Reason(
            "urgent",
            "Urgent call-outs",
            "a leak, no power, no heat, danger or anything needing someone today",
        ),
        Reason(
            "existing_job",
            "Existing jobs",
            "a job already booked or done: timing, follow-up, invoices",
        ),
        Reason("questions", "Questions", "hours, areas covered, prices"),
        _OTHER,
    ),
    bookings_label=None,
)

ESTATE = ReasonSet(
    template="estate",
    business="an estate agency",
    reasons=(
        Reason("viewings", "Viewings", "book a viewing"),
        Reason(
            "property_questions",
            "Questions about a property",
            "price, availability, features of a listed property",
        ),
        Reason(
            "selling",
            "Selling or letting",
            "valuations, selling or letting their own property",
        ),
        Reason(
            "changes",
            "Changes & cancellations",
            "move or cancel an existing viewing",
        ),
        _OTHER,
    ),
    bookings_label="viewings booked",
)

GENERAL = ReasonSet(
    template="general",
    business="a business",
    reasons=(
        Reason("appointments", "Appointments", "book a new appointment"),
        Reason("questions", "Questions", "hours, prices, services, directions"),
        Reason(
            "changes",
            "Changes & cancellations",
            "move or cancel an existing appointment",
        ),
        Reason(
            "speak_to_someone",
            "Speak to someone",
            "wanted a person, a callback or to leave a message",
        ),
        _OTHER,
    ),
    bookings_label="appointments booked",
)

REASON_SETS: dict[str, ReasonSet] = {
    s.template: s for s in (RESTAURANT, CLINIC, SALON, TRADES, ESTATE, GENERAL)
}
# Starter categories without a set of their own.
_ALIASES = {"telephony": "general"}


def reason_set(template: str | None) -> ReasonSet:
    """The set for a starter template category; general when unknown."""
    key = _ALIASES.get(template or "", template or "")
    return REASON_SETS.get(key, GENERAL)


def _prompts(definition: Mapping[str, Any] | None) -> list[str]:
    nodes = (definition or {}).get("nodes") if isinstance(definition, Mapping) else None
    prompts: list[str] = []
    for node in nodes if isinstance(nodes, list) else []:
        data = node.get("data") if isinstance(node, Mapping) else None
        prompt = data.get("prompt") if isinstance(data, Mapping) else None
        if isinstance(prompt, str):
            prompts.append(prompt)
    return prompts


def starter_marker(definition: Mapping[str, Any] | None) -> str | None:
    """The fixed opening words of a starter's instructions: the text of the
    first step prompt up to its first placeholder (``{{``). None when too
    short to tell starters apart."""
    for prompt in _prompts(definition):
        head = prompt.split("{{", 1)[0].strip()
        if "{{" in prompt and len(head) >= 20:
            return head
    return None


@lru_cache(maxsize=1)
def _starter_markers() -> tuple[tuple[str, str], ...]:
    from api.services.workflow.starter_templates import STARTER_TEMPLATES

    markers: list[tuple[str, str]] = []
    for starter in STARTER_TEMPLATES:
        if starter.call_type != "inbound":
            continue
        marker = starter_marker(starter.definition)
        if marker:
            markers.append((marker, starter.category))
    # Longest first, so a marker that starts another can't win by accident.
    return tuple(sorted(markers, key=lambda m: len(m[0]), reverse=True))


def template_for_workflow(
    definition: Mapping[str, Any] | None,
    facts: Mapping[str, Any] | None,
    markers: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Which starter template category an agent comes from (see module doc)."""
    stored = (facts or {}).get(TEMPLATE_CATEGORY_FACT)
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    markers = _starter_markers() if markers is None else markers
    text = "\n".join(_prompts(definition))
    if not text:
        text = json.dumps(definition or {})
    for marker, category in markers:
        if marker in text:
            return category
    return "general"

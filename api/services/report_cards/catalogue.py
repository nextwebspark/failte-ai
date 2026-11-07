"""Which cards each kind of business's report starts with.

A pack is picked from the agent's starter template (``template_category``,
see ``call_review.categories.template_for_workflow``). Every pack has the
shared cards; each adds its own. The owner can then switch cards off,
reorder them and pick what goes in the email (``layout.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from api.services.call_review.categories import ReasonSet, reason_set


class Pack(StrEnum):
    RESTAURANT = "restaurant"
    CLINIC = "clinic"
    TRADES = "trades"
    VOIP = "voip"
    # Every other template: the shared cards only.
    STANDARD = "standard"


class CardSize(StrEnum):
    # A headline number, shown in the row of tiles at the top.
    KPI = "kpi"
    PANEL = "panel"
    # A panel twice as wide on large screens (charts with many bars).
    WIDE = "wide"


class Card(StrEnum):
    # Shared
    CALLS_ANSWERED = "calls_answered"
    CALLERS_WANTED = "callers_wanted"
    BUSIEST_TIMES = "busiest_times"
    UNANSWERED_QUESTIONS = "unanswered_questions"
    FOLLOW_UPS = "follow_ups"
    AFTER_HOURS = "after_hours"
    AGENT_PERFORMANCE = "agent_performance"
    # Restaurant
    BOOKINGS_TAKEN = "bookings_taken"
    COVERS_BOOKED = "covers_booked"
    TABLES_FULL = "tables_full"
    DAYS_FILLING = "days_filling"
    SPECIAL_REQUESTS = "special_requests"
    TAKEAWAY = "takeaway"
    BOOKINGS_VALUE = "bookings_value"
    # Dental / GP clinic
    APPOINTMENTS_BOOKED = "appointments_booked"
    PATIENT_STATUS = "patient_status"
    APPOINTMENT_TYPES = "appointment_types"
    EMERGENCIES = "emergencies"
    CHANGES = "changes"
    APPOINTMENTS_VALUE = "appointments_value"
    # Trades
    JOBS_QUOTES = "jobs_quotes"
    EMERGENCIES_BY_HOUR = "emergencies_by_hour"
    AREAS = "areas"
    CALLBACKS_WAITING = "callbacks_waiting"
    AFTER_HOURS_CALLOUTS = "after_hours_callouts"
    JOBS_VALUE = "jobs_value"
    # VoIP / support line
    SORTED_BY_AGENT = "sorted_by_agent"
    PASSED_ON = "passed_on"
    ISSUES_BY_TYPE = "issues_by_type"
    CALL_SPIKES = "call_spikes"
    REPEAT_CALLERS = "repeat_callers"
    WAITING_FOR_TEAM = "waiting_for_team"


@dataclass(frozen=True, slots=True)
class CardSpec:
    key: Card
    title: str
    size: CardSize
    # In the email when the owner hasn't chosen.
    email: bool = False
    # Money estimate: shown only once the owner enters their own average.
    estimate: bool = False


@dataclass(frozen=True, slots=True)
class PackSpec:
    pack: Pack
    label: str
    cards: tuple[CardSpec, ...]
    # The owner's own average, for the money estimate: what it is "per".
    value_unit: str | None = None
    value_label: str | None = None

    @property
    def keys(self) -> tuple[Card, ...]:
        return tuple(c.key for c in self.cards)

    def spec(self, key: str) -> CardSpec | None:
        return next((c for c in self.cards if c.key == key), None)


_CALLS = CardSpec(Card.CALLS_ANSWERED, "Calls answered", CardSize.KPI, email=True)
_SHARED_PANELS = (
    CardSpec(
        Card.CALLERS_WANTED,
        "What callers wanted, day by day",
        CardSize.WIDE,
        email=True,
    ),
    CardSpec(Card.BUSIEST_TIMES, "Busiest times", CardSize.PANEL, email=True),
    CardSpec(
        Card.UNANSWERED_QUESTIONS,
        "Questions your agent couldn't answer",
        CardSize.PANEL,
        email=True,
    ),
    CardSpec(Card.FOLLOW_UPS, "Follow-ups", CardSize.PANEL, email=True),
    CardSpec(Card.AFTER_HOURS, "Calls while you were closed", CardSize.PANEL),
    CardSpec(Card.AGENT_PERFORMANCE, "How your agent did", CardSize.PANEL),
)


def _shared(*, after_questions: tuple[CardSpec, ...] = ()) -> tuple[CardSpec, ...]:
    wanted, busiest, questions, *rest = _SHARED_PANELS
    return (wanted, busiest, *after_questions, questions, *rest)


PACKS: dict[Pack, PackSpec] = {
    Pack.RESTAURANT: PackSpec(
        Pack.RESTAURANT,
        "Restaurant",
        (
            _CALLS,
            CardSpec(Card.BOOKINGS_TAKEN, "Bookings taken", CardSize.KPI, email=True),
            CardSpec(Card.COVERS_BOOKED, "Covers booked", CardSize.KPI, email=True),
            CardSpec(Card.TABLES_FULL, "Tables you couldn't fit", CardSize.KPI),
            CardSpec(Card.TAKEAWAY, "Takeaway orders", CardSize.KPI),
            CardSpec(
                Card.BOOKINGS_VALUE, "Bookings value", CardSize.KPI, estimate=True
            ),
            *_shared(
                after_questions=(
                    CardSpec(
                        Card.DAYS_FILLING, "Which days are filling up", CardSize.PANEL
                    ),
                )
            ),
            CardSpec(Card.SPECIAL_REQUESTS, "Special requests", CardSize.PANEL),
        ),
        value_unit="cover",
        value_label="Average spend per cover",
    ),
    Pack.CLINIC: PackSpec(
        Pack.CLINIC,
        "Dental / GP clinic",
        (
            _CALLS,
            CardSpec(
                Card.APPOINTMENTS_BOOKED,
                "Appointments booked",
                CardSize.KPI,
                email=True,
            ),
            CardSpec(Card.EMERGENCIES, "Emergencies", CardSize.KPI, email=True),
            CardSpec(Card.CHANGES, "Cancellations and moves", CardSize.KPI),
            CardSpec(
                Card.APPOINTMENTS_VALUE,
                "Appointments value",
                CardSize.KPI,
                estimate=True,
            ),
            *_shared(
                after_questions=(
                    CardSpec(
                        Card.PATIENT_STATUS, "New and existing patients", CardSize.PANEL
                    ),
                    CardSpec(
                        Card.APPOINTMENT_TYPES, "Appointment types", CardSize.PANEL
                    ),
                )
            ),
        ),
        value_unit="appointment",
        value_label="Average value per appointment",
    ),
    Pack.TRADES: PackSpec(
        Pack.TRADES,
        "Trades",
        (
            _CALLS,
            CardSpec(
                Card.JOBS_QUOTES, "Jobs and quotes requested", CardSize.KPI, email=True
            ),
            CardSpec(
                Card.AFTER_HOURS_CALLOUTS,
                "After-hours call-outs",
                CardSize.KPI,
                email=True,
            ),
            CardSpec(Card.JOBS_VALUE, "Jobs value", CardSize.KPI, estimate=True),
            *_shared(
                after_questions=(
                    CardSpec(
                        Card.CALLBACKS_WAITING,
                        "Callbacks still waiting",
                        CardSize.PANEL,
                        email=True,
                    ),
                    CardSpec(
                        Card.EMERGENCIES_BY_HOUR, "Emergencies by hour", CardSize.PANEL
                    ),
                    CardSpec(Card.AREAS, "Where calls come from", CardSize.PANEL),
                )
            ),
        ),
        value_unit="job",
        value_label="Average value per job",
    ),
    Pack.VOIP: PackSpec(
        Pack.VOIP,
        "VoIP / support line",
        (
            _CALLS,
            CardSpec(
                Card.SORTED_BY_AGENT, "Sorted by your agent", CardSize.KPI, email=True
            ),
            CardSpec(Card.PASSED_ON, "Passed to your team", CardSize.KPI, email=True),
            *_shared(
                after_questions=(
                    CardSpec(
                        Card.ISSUES_BY_TYPE,
                        "Issues by type",
                        CardSize.PANEL,
                        email=True,
                    ),
                    CardSpec(
                        Card.WAITING_FOR_TEAM,
                        "Waiting for your team",
                        CardSize.PANEL,
                        email=True,
                    ),
                    CardSpec(Card.CALL_SPIKES, "Call spikes by hour", CardSize.PANEL),
                    CardSpec(Card.REPEAT_CALLERS, "Repeat callers", CardSize.PANEL),
                )
            ),
        ),
    ),
}


def _standard(reasons: ReasonSet) -> PackSpec:
    cards: list[CardSpec] = [_CALLS]
    if reasons.bookings_label:
        cards.append(
            CardSpec(
                Card.BOOKINGS_TAKEN,
                reasons.bookings_label[:1].upper() + reasons.bookings_label[1:],
                CardSize.KPI,
                email=True,
            )
        )
    return PackSpec(Pack.STANDARD, "Standard", (*cards, *_shared()))


_TEMPLATE_PACKS = {
    "restaurant": Pack.RESTAURANT,
    "clinic": Pack.CLINIC,
    "trades": Pack.TRADES,
    "telephony": Pack.VOIP,
}


def pack_for_template(template: str | None) -> PackSpec:
    """The pack an agent made from *template* starts with."""
    pack = _TEMPLATE_PACKS.get(template or "")
    if pack is not None:
        return PACKS[pack]
    return _standard(reason_set(template))

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from api.schemas.appointment_hours import AppointmentHours

SETUP_VALUE_MAX_LENGTH = 2000


class SetupFieldType(StrEnum):
    """How the Create agent dialog asks a setup question."""

    TEXT = "text"
    TEXTAREA = "textarea"
    URL = "url"
    EMAIL = "email"
    PHONE = "phone"
    # Switches; the answer is the chosen option values, comma-separated.
    TOGGLES = "toggles"
    # Answered with the request's structured ``appointment_hours``.
    APPOINTMENT_HOURS = "appointment_hours"


class SetupOption(BaseModel):
    """One switch in a ``toggles`` question, e.g. "Party size"."""

    value: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    label: str = Field(min_length=1, max_length=80)
    prompt: str = Field(
        min_length=1,
        max_length=200,
        description="What the agent is told when it is on, e.g. 'how many people'.",
    )
    default: bool = False


class TemplateSetupField(BaseModel):
    """One question the Create agent dialog asks before copying a template.

    The answer replaces every ``{{key}}`` placeholder in the template. A
    placeholder may carry a fallback (``{{key | fallback:text}}``), which is
    used when an optional field is left empty.

    An ``appointment_hours`` field is answered with the request's structured
    ``appointment_hours`` (not with ``values``); its placeholder becomes a
    sentence describing those hours.
    """

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    label: str = Field(min_length=1, max_length=120)
    type: SetupFieldType = SetupFieldType.TEXT
    help: str | None = Field(default=None, max_length=300)
    placeholder: str | None = Field(default=None, max_length=300)
    required: bool = True
    max_length: int = Field(default=500, ge=1, le=SETUP_VALUE_MAX_LENGTH)
    # ``toggles`` only: the switches, and the sentence the chosen ones fill
    # ("{items}" becomes "how many people and about allergies"). The answer
    # is the chosen values, comma-separated; none chosen leaves the
    # placeholder empty.
    # Kept as an agent fact (template_context_variables) that the owner can
    # edit later on the Business facts screen, instead of being written
    # into the prompts; the prompts read it at call time.
    stored: bool = False
    options: list[SetupOption] = Field(default_factory=list, max_length=12)
    sentence: str = Field(default="Also ask {items}.", max_length=200)

    @model_validator(mode="after")
    def _options_only_for_toggles(self) -> Self:
        if self.type == "toggles":
            if not self.options:
                raise ValueError("a toggles question needs options")
            if len({o.value for o in self.options}) != len(self.options):
                raise ValueError("toggle values must be unique")
            if "{items}" not in self.sentence:
                raise ValueError("sentence must contain {items}")
        elif self.options:
            raise ValueError("only a toggles question has options")
        return self


class WorkflowTemplateResponse(BaseModel):
    id: int
    template_name: str
    template_description: str
    template_json: dict
    setup_fields: list[TemplateSetupField] = []
    # "inbound" or "outbound"; None when the template doesn't say.
    call_type: Literal["inbound", "outbound"] | None = None
    icon: str | None = None
    featured: bool = False
    sample_audio_url: str | None = None
    # Gallery filter group, e.g. "clinic", "trades", "restaurant", "estate".
    category: str | None = None
    # Integration providers the dialog offers to connect, e.g. "google-calendar".
    integrations: list[str] = []
    created_at: datetime


class DuplicateTemplateRequest(BaseModel):
    template_id: int
    workflow_name: str = Field(min_length=1, max_length=200)
    # Answers to the template's setup_fields, keyed by field key.
    values: dict[str, str] = Field(default_factory=dict)
    # The tool to attach for each of the template's integrations, keyed by
    # provider, e.g. {"google-calendar": "<tool uuid>"}. A template that
    # books with Google Calendar also takes {"calendly": "<tool uuid>"}.
    integration_tools: dict[str, str] = Field(default_factory=dict)
    appointment_hours: AppointmentHours | None = Field(
        default=None,
        description="Answer to the template's appointment_hours question; "
        "only with Google Calendar attached. Goes into the agent's prompt.",
    )
    apply_to_calendar: bool = Field(
        default=False,
        description="Also make appointment_hours the attached Google Calendar "
        "connection's booking hours (shared by every agent that books with it).",
    )

    @model_validator(mode="after")
    def _hours_to_apply(self) -> Self:
        if self.apply_to_calendar and self.appointment_hours is None:
            raise ValueError("apply_to_calendar needs appointment_hours")
        return self

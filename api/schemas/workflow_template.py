from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SETUP_VALUE_MAX_LENGTH = 2000


class TemplateSetupField(BaseModel):
    """One question the Create agent dialog asks before copying a template.

    The answer replaces every ``{{key}}`` placeholder in the template. A
    placeholder may carry a fallback (``{{key | fallback:text}}``), which is
    used when an optional field is left empty.
    """

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "textarea", "url", "email", "phone"] = "text"
    help: str | None = Field(default=None, max_length=300)
    placeholder: str | None = Field(default=None, max_length=300)
    required: bool = True
    max_length: int = Field(default=500, ge=1, le=SETUP_VALUE_MAX_LENGTH)


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
    # Integration providers the dialog offers to connect, e.g. "google-calendar".
    integrations: list[str] = []
    created_at: datetime


class DuplicateTemplateRequest(BaseModel):
    template_id: int
    workflow_name: str = Field(min_length=1, max_length=200)
    # Answers to the template's setup_fields, keyed by field key.
    values: dict[str, str] = Field(default_factory=dict)
    # The tool to attach for each of the template's integrations, keyed by
    # provider, e.g. {"google-calendar": "<tool uuid>"}.
    integration_tools: dict[str, str] = Field(default_factory=dict)

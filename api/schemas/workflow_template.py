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

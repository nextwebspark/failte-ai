"""Per-agent setting: email the business a summary after each useful call."""

from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.networks import validate_email

CALL_SUMMARY_EMAIL_KEY = "call_summary_email"
MAX_CALL_SUMMARY_RECIPIENTS = 5


def _email_address(value: str) -> str:
    return validate_email(value)[1]


# Validated like ``EmailStr`` but published as a plain string, so clients
# generated from the OpenAPI spec (the SDKs) need no email-validator package.
EmailAddress = Annotated[str, AfterValidator(_email_address)]


class CallSummaryEmailConfiguration(BaseModel):
    """Who hears about calls where the agent took a message or a booking."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=False,
        description=(
            "Email a summary after each phone call where the agent took a "
            "message or booked or cancelled an appointment."
        ),
    )
    recipients: list[EmailAddress] = Field(
        default_factory=list,
        max_length=MAX_CALL_SUMMARY_RECIPIENTS,
        description="Addresses that receive the summaries.",
    )

    @field_validator("recipients", mode="before")
    @classmethod
    def _drop_blank_recipients(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                item.strip() if isinstance(item, str) else item
                for item in value
                if not (isinstance(item, str) and not item.strip())
            ]
        return value

    @field_validator("recipients")
    @classmethod
    def _deduplicate_recipients(cls, value: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for address in value:
            if address.casefold() not in seen:
                seen.add(address.casefold())
                unique.append(address)
        return unique

    @model_validator(mode="after")
    def _require_a_recipient(self) -> Self:
        if self.enabled and not self.recipients:
            raise ValueError("call summaries need at least one email address")
        return self

from pydantic import BaseModel, EmailStr, Field, field_validator

MAX_EXTRA_RECIPIENTS = 10


class CallNotificationSettings(BaseModel):
    """Who hears about a workspace's calls. Stored per organization."""

    email_enabled: bool = Field(
        default=True, description="Email the business after calls at all."
    )
    email_on_booking: bool = Field(
        default=True,
        description="Email when the agent books, moves or cancels a booking.",
    )
    email_on_message: bool = Field(
        default=True, description="Email when the agent takes a message."
    )
    email_on_missed_call: bool = Field(
        default=True, description="Email when a caller couldn't be helped."
    )
    email_members: bool = Field(
        default=True,
        description="Send the emails to the workspace's owners and admins.",
    )
    extra_recipients: list[EmailStr] = Field(
        default_factory=list,
        max_length=MAX_EXTRA_RECIPIENTS,
        description="More addresses that get the same emails.",
    )
    text_caller_booking_confirmation: bool = Field(
        default=True,
        description=(
            "Text the caller when the calendar confirms their booking. Only "
            "sent once a text provider is set up for this install."
        ),
    )

    @field_validator("extra_recipients", mode="after")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        unique = []
        for address in value:
            key = address.lower()
            if key not in seen:
                seen.add(key)
                unique.append(address)
        return unique


class CallNotificationSettingsResponse(CallNotificationSettings):
    member_recipients: list[str] = Field(
        default_factory=list,
        description="The owners' and admins' addresses (used when email_members).",
    )
    email_available: bool = Field(
        description="An email provider is set up, so emails actually go out."
    )
    sms_available: bool = Field(
        description="A text provider is set up, so caller texts actually go out."
    )

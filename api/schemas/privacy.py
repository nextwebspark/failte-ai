"""Request and response types for account and organisation deletion and export."""

from datetime import datetime

from pydantic import BaseModel, Field


class DeleteAccountRequest(BaseModel):
    confirm_email: str = Field(
        description=(
            "The account's email address, typed to confirm (DELETE for an "
            "account without one)."
        )
    )


class DeleteOrganizationRequest(BaseModel):
    confirm_name: str = Field(description="The organization's name, typed to confirm.")


class OrganizationDeletionStatus(BaseModel):
    """Whether the selected organization is scheduled for deletion."""

    pending: bool
    requested_at: datetime | None = None
    scheduled_for: datetime | None = Field(
        default=None,
        description=(
            "When the organization and its data are permanently erased. Until "
            "then an admin can cancel the deletion."
        ),
    )

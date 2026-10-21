"""Domain errors for account and organization deletion (GDPR Art. 17).

Raised by the db/ and services/ layers; see ``api.errors.domain``. The UI
branches on ``code``.
"""

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from api.errors.domain import DomainError


class PrivacyError(DomainError):
    """Base class for deletion rule violations."""


class OrganizationPendingDeletionError(PrivacyError):
    """The organization is scheduled for deletion; its API is closed."""

    status_code = 423
    code = "organization_pending_deletion"

    def __init__(self, scheduled_for: datetime | None) -> None:
        when = f" on {scheduled_for:%Y-%m-%d}" if scheduled_for else ""
        super().__init__(
            f"This organization is scheduled for deletion{when}. An admin can "
            "cancel the deletion in Settings until then."
        )
        self.extra: Mapping[str, str] = MappingProxyType(
            {"deletion_scheduled_for": scheduled_for.isoformat()}
            if scheduled_for
            else {}
        )


class OrganizationErasedError(PrivacyError):
    """The organization has been erased; only its billing tombstone remains."""

    status_code = 410
    code = "organization_erased"

    def __init__(self) -> None:
        super().__init__("This organization has been deleted.")


class OrganizationDeletionNotPendingError(PrivacyError):
    status_code = 409
    code = "organization_deletion_not_pending"

    def __init__(self) -> None:
        super().__init__("This organization is not scheduled for deletion.")


class OrganizationErasureStartedError(PrivacyError):
    status_code = 409
    code = "organization_erasure_started"

    def __init__(self) -> None:
        super().__init__(
            "The grace period has ended and erasure has started; it can no "
            "longer be cancelled."
        )


class ConfirmationMismatchError(PrivacyError):
    status_code = 400
    code = "confirmation_mismatch"


class LastAdminWithMembersError(PrivacyError):
    """The user is the only admin of an organization that has other members."""

    status_code = 409
    code = "last_admin_of_organization"

    def __init__(self, organization_id: int, organization_name: str | None) -> None:
        name = organization_name or f"organization {organization_id}"
        super().__init__(
            f"You are the only admin of {name}, which has other members. Make "
            "another member an admin, or delete the organization, before "
            "deleting your account."
        )
        self.extra = MappingProxyType({"organization_id": str(organization_id)})


class SoleMemberOfOrganizationError(PrivacyError):
    """The user is the only member of an organization that would be orphaned."""

    status_code = 409
    code = "sole_member_of_organization"

    def __init__(self, organization_id: int, organization_name: str | None) -> None:
        name = organization_name or f"organization {organization_id}"
        super().__init__(
            f"You are the only member of {name}. Delete the organization first; "
            "you can then delete your account."
        )
        self.extra = MappingProxyType({"organization_id": str(organization_id)})


class IdentityProviderError(PrivacyError):
    """The external identity provider refused or failed the deletion."""

    status_code = 502
    code = "identity_provider_error"

    def __init__(self) -> None:
        super().__init__(
            "Your sign-in account could not be deleted right now. Nothing was "
            "deleted; please try again."
        )

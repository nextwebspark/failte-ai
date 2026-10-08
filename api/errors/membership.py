"""Domain errors for organization membership and role management.

Raised by the db/ and services/ layers; see ``api.errors.domain``.
"""

from api.errors.domain import DomainError


class MembershipError(DomainError):
    """Base class for membership rule violations."""


class MemberNotFoundError(MembershipError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Member not found in this organization")


class LastAdminError(MembershipError):
    """The change would leave the organization without any admin."""

    status_code = 409

    def __init__(self) -> None:
        super().__init__("An organization must keep at least one admin")


class OrganizationAccessDeniedError(MembershipError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__("You are not a member of this organization")


class AlreadyMemberError(MembershipError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("This user is already a member of the organization")

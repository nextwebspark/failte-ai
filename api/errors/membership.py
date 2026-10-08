"""Domain errors for organization membership and role management.

Raised by the db/ and services/ layers and mapped to HTTP responses once, in
``api.app``. Nothing here depends on FastAPI.
"""


class MembershipError(Exception):
    """Base class for membership rule violations."""

    status_code: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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

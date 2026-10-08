"""Domain errors for organization invitations; see ``api.errors.domain``."""

from api.errors.domain import DomainError


class InvitationError(DomainError):
    """Base class for invitation rule violations."""


class InvitationNotFoundError(InvitationError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Invitation not found")


class InvitationNotUsableError(InvitationError):
    """The invitation was already accepted, revoked, or has expired."""

    status_code = 410

    def __init__(self) -> None:
        super().__init__("This invitation is no longer valid")


class InvitationEmailMismatchError(InvitationError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__("This invitation was sent to a different email address")


class InvitationRateLimitError(InvitationError):
    status_code = 429

    def __init__(self) -> None:
        super().__init__("Too many invitations sent recently; try again later")

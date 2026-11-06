"""Domain errors for the platform admin area; see ``api.errors.domain``."""

from api.errors.domain import DomainError


class PlatformAdminError(DomainError):
    """Base class for platform admin rule violations."""


class PlatformUserNotFoundError(PlatformAdminError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("User not found")


class LastPlatformAdminError(PlatformAdminError):
    """Revoking would leave the platform with no platform admin."""

    status_code = 409

    def __init__(self) -> None:
        super().__init__("The platform must keep at least one platform admin")


class SelfDemotionError(PlatformAdminError):
    """A platform admin cannot revoke their own access (ask another admin)."""

    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            "You cannot remove your own platform admin access; ask another admin"
        )

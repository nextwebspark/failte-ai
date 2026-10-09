"""Domain errors for catalog integrations; see ``api.errors.domain``.

Messages are client-facing. They never include connection secrets or keys.
"""

from api.errors.domain import DomainError


class IntegrationError(DomainError):
    """Base class for catalog-integration failures."""


class ToolsServiceNotConfiguredError(IntegrationError):
    status_code = 503
    code = "tools_service_not_configured"

    def __init__(self) -> None:
        super().__init__(
            "Integrations are not available: the tools service is not "
            "configured on this deployment (set TOOLS_SERVICE_URL and "
            "TOOLS_INTERNAL_SECRET)."
        )


class ToolsServiceUnavailableError(IntegrationError):
    """The tools service could not be reached or failed unexpectedly."""

    status_code = 502
    code = "tools_service_unavailable"

    def __init__(self, message: str = "The tools service is unavailable") -> None:
        super().__init__(message)


class IntegrationNotFoundError(IntegrationError):
    status_code = 404
    code = "integration_not_found"


class IntegrationConflictError(IntegrationError):
    status_code = 409
    code = "integration_conflict"


class IntegrationInvalidRequestError(IntegrationError):
    status_code = 422
    code = "integration_invalid_request"


class IntegrationToolError(IntegrationError):
    """Creating the integration's tool was refused; keeps the cause's status."""

    code = "integration_tool_rejected"

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code

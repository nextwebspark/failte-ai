"""Errors raised at the Model Proxy Service boundary."""

MPS_UNAVAILABLE_PUBLIC_MESSAGE = (
    "A LightMove.ai service is temporarily unavailable. Please try again later."
)


class MPSUnavailableError(ConnectionError):
    """MPS could not complete an operation for a platform-owned reason.

    ``status_code`` is retained as structured classifier input. Response bodies are
    deliberately excluded because upstream payloads may contain sensitive details.
    """

    def __init__(self, operation: str, *, status_code: int | None = None) -> None:
        self.operation = operation
        self.status_code = status_code
        detail = f"MPS could not complete {operation}"
        if status_code is not None:
            detail = f"{detail} (HTTP {status_code})"
        super().__init__(detail)


MPS_NOT_CONFIGURED_PUBLIC_MESSAGE = "This feature isn't available on this server."


class MPSNotConfiguredError(MPSUnavailableError):
    """No MPS is configured (``MPS_API_URL`` is unset), so no call was made.

    Raised before any request is built, so nothing leaves the server. Callers
    gate MPS-only features on ``mps_service_key_client.is_configured``; this is
    the fail-closed backstop for any path that does not.
    """

    def __init__(self) -> None:
        super().__init__("an operation: MPS_API_URL is not configured")

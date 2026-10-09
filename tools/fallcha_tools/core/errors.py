"""Domain errors. ``app.py`` maps each class to an HTTP status in one place."""

from __future__ import annotations

from pydantic import ValidationError


class ToolsError(Exception):
    """Base class for expected, client-facing failures."""


class NotFoundError(ToolsError):
    """The resource does not exist, or is not visible to the caller's org."""


class ConflictError(ToolsError):
    """The resource is in a state that forbids the operation."""


class InvalidRequestError(ToolsError):
    """The request is well-formed but semantically invalid."""


def describe_validation_error(exc: ValidationError) -> str:
    """``loc: reason; ...`` without input values (they may be secret)."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'value'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    )

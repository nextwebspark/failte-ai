"""Domain errors. ``app.py`` maps each class to an HTTP status in one place."""

from __future__ import annotations


class ToolsError(Exception):
    """Base class for expected, client-facing failures."""


class NotFoundError(ToolsError):
    """The resource does not exist, or is not visible to the caller's org."""


class ConflictError(ToolsError):
    """The resource is in a state that forbids the operation."""


class InvalidRequestError(ToolsError):
    """The request is well-formed but semantically invalid."""

"""Base class for business-rule errors raised below the HTTP layer.

Services and DB clients raise subclasses; ``api.app`` maps every
``DomainError`` to a JSON response with its ``status_code`` in one handler, so
nothing outside ``routes/`` needs to import FastAPI. ``code`` is a stable
machine-readable identifier for clients that branch on the error; ``extra``
adds further machine-readable string fields to the response body.
"""

from collections.abc import Mapping
from types import MappingProxyType


class DomainError(Exception):
    status_code: int = 400
    code: str | None = None
    extra: Mapping[str, str] = MappingProxyType({})

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

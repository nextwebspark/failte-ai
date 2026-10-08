"""Base class for business-rule errors raised below the HTTP layer.

Services and DB clients raise subclasses; ``api.app`` maps every
``DomainError`` to a JSON response with its ``status_code`` in one handler, so
nothing outside ``routes/`` needs to import FastAPI.
"""


class DomainError(Exception):
    status_code: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

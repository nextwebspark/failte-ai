"""Domain errors for agent skills; see ``api.errors.domain``.

Messages are client-facing and name the offending field, path or key.
"""

from api.errors.domain import DomainError


class SkillError(DomainError):
    """Base class for skill failures."""


class SkillValidationError(SkillError):
    """A name, description, body, file, frontmatter or archive is invalid."""

    status_code = 422
    code = "skill_invalid"


class SkillNotFoundError(SkillError):
    status_code = 404
    code = "skill_not_found"

    def __init__(self, message: str = "Skill not found") -> None:
        super().__init__(message)


class LibrarySkillNotFoundError(SkillError):
    status_code = 404
    code = "library_skill_not_found"

    def __init__(self, message: str = "Library skill not found") -> None:
        super().__init__(message)


class SkillNameConflictError(SkillError):
    """The name is already used by another active skill in the same scope."""

    status_code = 409
    code = "skill_name_conflict"

    def __init__(self, name: str, *, suggestion: str | None = None) -> None:
        message = f"A skill named '{name}' already exists"
        if suggestion:
            message += f"; try '{suggestion}'"
        super().__init__(message)
        self.name = name
        self.suggestion = suggestion
        if suggestion:
            self.extra = {"suggested_name": suggestion}


class SkillStateError(SkillError):
    """The operation does not apply to the skill in its current state (e.g.
    copying an unpublished library skill, updating a modified copy without
    ``force``)."""

    status_code = 409
    code = "skill_state_conflict"

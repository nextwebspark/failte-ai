"""Validation shared by every way a skill enters the system (API, zip import,
library seeds).

Limits follow the Agent Skills specification (agentskills.io/specification)
where it sets one:

- ``name``: 1-64 characters, lowercase letters, digits and single hyphens,
  not starting or ending with a hyphen (``^[a-z0-9]+(-[a-z0-9]+)*$``).
- ``description``: 1-1024 characters, non-empty. Like the Claude API we also
  reject XML-style tags, since descriptions are injected into the agent's
  system prompt.
- ``compatibility``: at most 500 characters.
- ``metadata``: a string-to-string map.

The remaining limits are ours, sized for voice-agent playbooks that are read
into a live call's context: the body is at most 64 KB, and a skill has at most
20 reference files of at most 256 KB each and 1 MB together. Files are UTF-8
text only (no NUL bytes); executable scripts and binary assets are out of
scope for v1.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from api.db.skill_client import FrontmatterExtra, SkillContent, SkillFile
from api.errors.skills import SkillValidationError

NAME_MAX = 64
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DESCRIPTION_MAX = 1024
BODY_MAX_BYTES = 64 * 1024
MAX_FILES = 20
FILE_MAX_BYTES = 256 * 1024
FILES_TOTAL_MAX_BYTES = 1024 * 1024
PATH_MAX = 255
PATH_MAX_DEPTH = 8
LICENSE_MAX = 256
COMPATIBILITY_MAX = 500
METADATA_MAX_KEYS = 32
METADATA_KEY_MAX = 64
METADATA_VALUE_MAX = 1024
CATEGORY_MAX = 64
MAX_ALLOWED_TOOLS = 50
SKILL_FILE_NAME = "SKILL.md"

_XML_TAG = re.compile(r"</?[A-Za-z][\w:.-]*(\s[^<>]*)?/?>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True, slots=True)
class SkillLimits:
    """Archive limits; content limits are the module constants above."""

    max_archive_bytes: int = 2 * 1024 * 1024
    max_archive_entries: int = 64
    max_compression_ratio: int = 100


DEFAULT_LIMITS = SkillLimits()


def validate_name(name: str) -> str:
    if not name:
        raise SkillValidationError("Skill name is required")
    if len(name) > NAME_MAX:
        raise SkillValidationError(f"Skill name must be at most {NAME_MAX} characters")
    if not NAME_PATTERN.fullmatch(name):
        raise SkillValidationError(
            f"Invalid skill name '{_preview(name)}': use lowercase letters, digits "
            "and single hyphens, not starting or ending with a hyphen "
            "(e.g. 'returns-policy')"
        )
    return name


def validate_description(description: str) -> str:
    description = description.strip()
    if not description:
        raise SkillValidationError("Skill description is required")
    if len(description) > DESCRIPTION_MAX:
        raise SkillValidationError(
            f"Skill description must be at most {DESCRIPTION_MAX} characters"
        )
    if _XML_TAG.search(description):
        raise SkillValidationError("Skill description must not contain XML tags")
    return description


def validate_body(body_md: str) -> str:
    body = body_md.replace("\r\n", "\n").strip("\n")
    if not body.strip():
        raise SkillValidationError("Skill body (SKILL.md instructions) is required")
    if len(body.encode("utf-8")) > BODY_MAX_BYTES:
        raise SkillValidationError(
            f"Skill body must be at most {BODY_MAX_BYTES // 1024} KB"
        )
    _require_text(body, "SKILL.md")
    return body


def validate_path(path: str) -> str:
    """A normalized relative POSIX path inside the skill folder.

    Rejected rather than repaired: absolute paths, drive letters,
    backslashes, ``.``/``..`` or empty segments, hidden segments (leading
    ``.``), control characters, and ``SKILL.md`` at the root (that is the
    body).
    """
    path = unicodedata.normalize("NFC", path)
    shown = _preview(path)
    if not path:
        raise SkillValidationError("File path is required")
    if len(path) > PATH_MAX:
        raise SkillValidationError(f"File path is longer than {PATH_MAX} characters")
    if _CONTROL.search(path):
        raise SkillValidationError(f"File path '{shown}' contains control characters")
    if "\\" in path:
        raise SkillValidationError(
            f"File path '{shown}' must use '/' separators, not backslashes"
        )
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise SkillValidationError(f"File path '{shown}' must be relative")
    segments = path.split("/")
    if len(segments) > PATH_MAX_DEPTH:
        raise SkillValidationError(
            f"File path '{shown}' is nested deeper than {PATH_MAX_DEPTH} levels"
        )
    for segment in segments:
        if segment in ("", ".", ".."):
            raise SkillValidationError(
                f"File path '{shown}' must not contain empty, '.' or '..' segments"
            )
        if segment.startswith("."):
            raise SkillValidationError(
                f"File path '{shown}' must not contain hidden files or folders"
            )
    if path.lower() == SKILL_FILE_NAME.lower():
        raise SkillValidationError(
            "SKILL.md is the skill body; send it as body_md, not as a file"
        )
    return path


def validate_files(files: Iterable[SkillFile]) -> tuple[SkillFile, ...]:
    """Validate paths, sizes and text-ness; returns the files sorted by path."""
    result: list[SkillFile] = []
    seen: set[str] = set()
    total = 0
    for item in files:
        path = validate_path(item.path)
        key = path.lower()
        if key in seen:
            raise SkillValidationError(f"Duplicate file path '{_preview(path)}'")
        seen.add(key)
        content = item.content.replace("\r\n", "\n")
        size = len(content.encode("utf-8"))
        if size > FILE_MAX_BYTES:
            raise SkillValidationError(
                f"File '{_preview(path)}' is larger than {FILE_MAX_BYTES // 1024} KB"
            )
        _require_text(content, path)
        total += size
        result.append(SkillFile(path=path, content=content))
    if len(result) > MAX_FILES:
        raise SkillValidationError(f"A skill can have at most {MAX_FILES} files")
    if total > FILES_TOTAL_MAX_BYTES:
        raise SkillValidationError(
            f"Skill files must total at most {FILES_TOTAL_MAX_BYTES // 1024} KB"
        )
    return tuple(sorted(result, key=lambda f: f.path))


def validate_extra(extra: FrontmatterExtra) -> FrontmatterExtra:
    license_ = extra.license.strip() if extra.license is not None else None
    if license_ is not None and len(license_) > LICENSE_MAX:
        raise SkillValidationError(f"license must be at most {LICENSE_MAX} characters")
    compatibility = (
        extra.compatibility.strip() if extra.compatibility is not None else None
    )
    if compatibility is not None and len(compatibility) > COMPATIBILITY_MAX:
        raise SkillValidationError(
            f"compatibility must be at most {COMPATIBILITY_MAX} characters"
        )
    if len(extra.metadata) > METADATA_MAX_KEYS:
        raise SkillValidationError(
            f"metadata can have at most {METADATA_MAX_KEYS} entries"
        )
    for key, value in extra.metadata.items():
        if not key or len(key) > METADATA_KEY_MAX:
            raise SkillValidationError(
                f"metadata keys must be 1-{METADATA_KEY_MAX} characters"
            )
        if len(value) > METADATA_VALUE_MAX:
            raise SkillValidationError(
                f"metadata value for '{_preview(key)}' must be at most "
                f"{METADATA_VALUE_MAX} characters"
            )
    return FrontmatterExtra(
        license=license_ or None,
        compatibility=compatibility or None,
        metadata=dict(extra.metadata),
    )


def validate_content(content: SkillContent) -> SkillContent:
    return SkillContent(
        name=validate_name(content.name),
        description=validate_description(content.description),
        body_md=validate_body(content.body_md),
        files=validate_files(content.files),
        extra=validate_extra(content.extra),
    )


def validate_category(category: str | None) -> str | None:
    if category is None:
        return None
    category = category.strip()
    if not category:
        return None
    if len(category) > CATEGORY_MAX:
        raise SkillValidationError(
            f"category must be at most {CATEGORY_MAX} characters"
        )
    return category


def normalize_tool_uuids(tool_uuids: Iterable[str]) -> tuple[str, ...]:
    """De-duplicated, order-preserving; existence is checked by the caller."""
    result: list[str] = []
    for tool_uuid in tool_uuids:
        tool_uuid = tool_uuid.strip()
        if tool_uuid and tool_uuid not in result:
            result.append(tool_uuid)
    if len(result) > MAX_ALLOWED_TOOLS:
        raise SkillValidationError(
            f"A skill can allow at most {MAX_ALLOWED_TOOLS} tools"
        )
    return tuple(result)


def suggest_name(base: str, taken: set[str]) -> str:
    """The first ``<base>-N`` (N >= 2) not in ``taken``, within NAME_MAX."""
    for n in range(2, 1000):
        suffix = f"-{n}"
        candidate = base[: NAME_MAX - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
    raise SkillValidationError("Could not find a free skill name")


def _require_text(content: str, label: str) -> None:
    if _TEXT_CONTROL.search(content):
        raise SkillValidationError(
            f"'{_preview(label)}' is not a text file (binary content is not supported)"
        )


def _preview(value: str, limit: int = 80) -> str:
    """Bounded, control-free echo of user input for error messages."""
    cleaned = _CONTROL.sub("?", value)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."

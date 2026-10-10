"""Parse and serialise ``SKILL.md`` (YAML frontmatter + markdown body).

Frontmatter keys follow the Agent Skills specification:

- required: ``name``, ``description``;
- optional: ``license``, ``compatibility``, ``metadata`` (string map, scalar
  values are coerced to strings), ``allowed-tools`` (space-delimited string
  or YAML list).

Any other top-level key is **rejected** with an error that names it, rather
than silently dropped or stored: an unknown key may carry behaviour (e.g.
Claude Code's ``model``) that we would otherwise ignore without telling the
author. Custom data belongs under ``metadata``, which round-trips.

``allowed-tools`` entries are returned as-is; mapping them to workspace tool
UUIDs (and rejecting unknown ones) is the caller's job.

YAML is read with ``yaml.safe_load`` only, after a size cap, so no Python
objects are constructed and alias expansion stays bounded.
"""

from dataclasses import dataclass, field
from typing import Any

import yaml  # type: ignore[import-untyped]

from api.db.skill_client import FrontmatterExtra, SkillContent
from api.errors.skills import SkillValidationError

FRONTMATTER_MAX_BYTES = 16 * 1024
_DELIMITER = "---"
_SUPPORTED_KEYS = (
    "name",
    "description",
    "license",
    "compatibility",
    "allowed-tools",
    "metadata",
)


@dataclass(frozen=True, slots=True)
class SkillDocument:
    """A parsed ``SKILL.md``: content without files, plus ``allowed-tools``."""

    content: SkillContent
    allowed_tools: tuple[str, ...] = field(default=())


def parse_skill_md(text: str) -> SkillDocument:
    """Split and validate the frontmatter's shape; field values are checked
    by ``api.services.skills.validation``."""
    text = text.removeprefix("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != _DELIMITER:
        raise SkillValidationError(
            "SKILL.md must start with YAML frontmatter between '---' lines"
        )
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _DELIMITER)
    except StopIteration:
        raise SkillValidationError(
            "SKILL.md frontmatter is not closed with a '---' line"
        ) from None
    raw = "\n".join(lines[1:end])
    if len(raw.encode("utf-8")) > FRONTMATTER_MAX_BYTES:
        raise SkillValidationError(
            f"SKILL.md frontmatter must be at most {FRONTMATTER_MAX_BYTES // 1024} KB"
        )
    data = _load_yaml(raw)
    unknown = [key for key in data if key not in _SUPPORTED_KEYS]
    if unknown:
        raise SkillValidationError(
            "Unsupported SKILL.md frontmatter keys: "
            + ", ".join(sorted(unknown))
            + ". Supported: "
            + ", ".join(_SUPPORTED_KEYS)
            + ". Put custom fields under 'metadata'."
        )
    body = "\n".join(lines[end + 1 :]).strip("\n")
    return SkillDocument(
        content=SkillContent(
            name=_required_str(data, "name"),
            description=_required_str(data, "description"),
            body_md=body,
            extra=FrontmatterExtra(
                license=_optional_str(data, "license"),
                compatibility=_optional_str(data, "compatibility"),
                metadata=_metadata(data.get("metadata")),
            ),
        ),
        allowed_tools=_allowed_tools(data.get("allowed-tools")),
    )


def render_skill_md(
    content: SkillContent, *, allowed_tools: tuple[str, ...] | None = None
) -> str:
    """The inverse of ``parse_skill_md`` for validated content."""
    data: dict[str, Any] = {
        "name": content.name,
        "description": content.description,
    }
    if content.extra.license is not None:
        data["license"] = content.extra.license
    if content.extra.compatibility is not None:
        data["compatibility"] = content.extra.compatibility
    if allowed_tools:
        data["allowed-tools"] = " ".join(allowed_tools)
    if content.extra.metadata:
        data["metadata"] = dict(content.extra.metadata)
    header = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000
    )
    return f"{_DELIMITER}\n{header}{_DELIMITER}\n\n{content.body_md}\n"


def _load_yaml(raw: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 2})" if mark is not None else ""
        raise SkillValidationError(
            f"SKILL.md frontmatter is not valid YAML{where}"
        ) from None
    if data is None:
        data = {}
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise SkillValidationError("SKILL.md frontmatter must be a YAML mapping")
    return data


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        raise SkillValidationError(f"SKILL.md frontmatter is missing '{key}'")
    if not isinstance(value, str):
        raise SkillValidationError(f"SKILL.md frontmatter '{key}' must be a string")
    return value


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillValidationError(f"SKILL.md frontmatter '{key}' must be a string")
    return value


def _scalar_str(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _metadata(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SkillValidationError("SKILL.md frontmatter 'metadata' must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        text = _scalar_str(item)
        if not isinstance(key, str) or text is None:
            raise SkillValidationError(
                "SKILL.md frontmatter 'metadata' must map strings to strings"
            )
        result[key] = text
    return result


def _allowed_tools(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(token for token in value.split() if token)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(v.strip() for v in value if v.strip())
    raise SkillValidationError(
        "SKILL.md frontmatter 'allowed-tools' must be a space-separated string "
        "or a list of strings"
    )

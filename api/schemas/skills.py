"""Request/response schemas for agent skills (``/skills``, ``/skill-library``).

Shapes only, with generous size guards; the content rules (name pattern,
description and body limits, file paths and sizes) live in
``api.services.skills.validation`` so the API, zip import and library seeds
share them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.db.skill_client import (
    FrontmatterExtra,
    LibrarySkill,
    SkillContent,
    SkillFile,
    WorkspaceSkill,
)
from api.db.skill_models import LibrarySkillStatus, SkillStatus

# Coarse request-size guards; precise limits are enforced by the service.
_TEXT_GUARD = 300 * 1024
_FILES_GUARD = 64


class SkillFileBody(BaseModel):
    path: str = Field(max_length=1024, examples=["references/returns-policy.md"])
    content: str = Field(max_length=_TEXT_GUARD)

    def to_file(self) -> SkillFile:
        return SkillFile(path=self.path, content=self.content)


class SkillFrontmatterExtra(BaseModel):
    """Optional Agent Skills frontmatter fields, kept for export."""

    license: str | None = Field(default=None, max_length=1024)
    compatibility: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_extra(self) -> FrontmatterExtra:
        return FrontmatterExtra(
            license=self.license,
            compatibility=self.compatibility,
            metadata=dict(self.metadata),
        )

    @classmethod
    def from_extra(cls, extra: FrontmatterExtra) -> SkillFrontmatterExtra:
        return cls(
            license=extra.license,
            compatibility=extra.compatibility,
            metadata=dict(extra.metadata),
        )


class _SkillContentRequest(BaseModel):
    name: str = Field(
        max_length=256,
        description="Kebab-case, 1-64 characters, e.g. 'returns-policy'.",
    )
    description: str = Field(
        max_length=4096,
        description="1-1024 characters; tells the agent when to load the skill.",
    )
    body_md: str = Field(
        max_length=_TEXT_GUARD,
        description="SKILL.md instructions (markdown, no frontmatter).",
    )
    files: list[SkillFileBody] = Field(default_factory=list, max_length=_FILES_GUARD)
    frontmatter_extra: SkillFrontmatterExtra | None = None

    def to_content(self) -> SkillContent:
        return SkillContent(
            name=self.name,
            description=self.description,
            body_md=self.body_md,
            files=tuple(f.to_file() for f in self.files),
            extra=(
                self.frontmatter_extra.to_extra()
                if self.frontmatter_extra
                else FrontmatterExtra()
            ),
        )


class CreateSkillRequest(_SkillContentRequest):
    allowed_tool_uuids: list[str] | None = Field(
        default=None,
        max_length=100,
        description="Tools this skill may use once loaded; null for no restriction.",
    )


class UpdateSkillRequest(BaseModel):
    """Partial update. ``files`` replaces the whole file set;
    ``allowed_tool_uuids: null`` clears the restriction."""

    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    body_md: str | None = Field(default=None, max_length=_TEXT_GUARD)
    files: list[SkillFileBody] | None = Field(default=None, max_length=_FILES_GUARD)
    frontmatter_extra: SkillFrontmatterExtra | None = None
    allowed_tool_uuids: list[str] | None = Field(default=None, max_length=100)


class CopyLibrarySkillRequest(BaseModel):
    name: str | None = Field(
        default=None,
        max_length=256,
        description="Name for the workspace copy; defaults to the library name.",
    )


class ApplyLibraryUpdateRequest(BaseModel):
    strategy: Literal["replace"] = "replace"
    force: bool = Field(
        default=False,
        description="Replace the content even though the copy was edited.",
    )


class SkillSummaryResponse(BaseModel):
    skill_uuid: str
    name: str
    description: str
    status: SkillStatus
    allowed_tool_uuids: list[str] | None
    source_library_uuid: str | None
    source_version: int | None
    is_modified: bool
    update_available: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_skill(cls, skill: WorkspaceSkill) -> SkillSummaryResponse:
        return cls(
            skill_uuid=skill.skill_uuid,
            name=skill.content.name,
            description=skill.content.description,
            status=skill.status,
            allowed_tool_uuids=(
                list(skill.allowed_tool_uuids)
                if skill.allowed_tool_uuids is not None
                else None
            ),
            source_library_uuid=skill.source_library_uuid,
            source_version=skill.source_version,
            is_modified=skill.is_modified,
            update_available=skill.update_available,
            created_by=skill.created_by,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )


class SkillResponse(SkillSummaryResponse):
    body_md: str
    files: list[SkillFileBody]
    frontmatter_extra: SkillFrontmatterExtra

    @classmethod
    def from_skill(cls, skill: WorkspaceSkill) -> SkillResponse:
        summary = SkillSummaryResponse.from_skill(skill)
        return cls(
            **summary.model_dump(),
            body_md=skill.content.body_md,
            files=[
                SkillFileBody(path=f.path, content=f.content)
                for f in skill.content.files
            ],
            frontmatter_extra=SkillFrontmatterExtra.from_extra(skill.content.extra),
        )


class SkillListResponse(BaseModel):
    skills: list[SkillSummaryResponse]


class LibraryDiffResponse(BaseModel):
    skill_uuid: str
    library_skill_uuid: str
    source_version: int | None
    latest_version: int
    library_status: LibrarySkillStatus
    is_modified: bool
    update_available: bool
    diff: str = Field(
        description="Unified diff from the workspace copy (a/) to the latest "
        "library version (b/); empty when they match."
    )


# -- library ---------------------------------------------------------------------


class CreateLibrarySkillRequest(_SkillContentRequest):
    category: str | None = Field(default=None, max_length=256)


class UpdateLibrarySkillRequest(BaseModel):
    """Partial update; ``files`` replaces the whole file set. Editing the
    content of a published skill publishes a new version."""

    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    body_md: str | None = Field(default=None, max_length=_TEXT_GUARD)
    files: list[SkillFileBody] | None = Field(default=None, max_length=_FILES_GUARD)
    frontmatter_extra: SkillFrontmatterExtra | None = None
    category: str | None = Field(default=None, max_length=256)


class LibrarySkillSummaryResponse(BaseModel):
    library_skill_uuid: str
    name: str
    description: str
    version: int
    status: LibrarySkillStatus
    category: str | None
    is_seeded: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_skill(cls, skill: LibrarySkill) -> LibrarySkillSummaryResponse:
        return cls(
            library_skill_uuid=skill.library_skill_uuid,
            name=skill.content.name,
            description=skill.content.description,
            version=skill.version,
            status=skill.status,
            category=skill.category,
            is_seeded=skill.is_seeded,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )


class LibrarySkillResponse(LibrarySkillSummaryResponse):
    body_md: str
    files: list[SkillFileBody]
    frontmatter_extra: SkillFrontmatterExtra

    @classmethod
    def from_skill(cls, skill: LibrarySkill) -> LibrarySkillResponse:
        summary = LibrarySkillSummaryResponse.from_skill(skill)
        return cls(
            **summary.model_dump(),
            body_md=skill.content.body_md,
            files=[
                SkillFileBody(path=f.path, content=f.content)
                for f in skill.content.files
            ],
            frontmatter_extra=SkillFrontmatterExtra.from_extra(skill.content.extra),
        )


class LibrarySkillListResponse(BaseModel):
    skills: list[LibrarySkillSummaryResponse]


class SeedSyncResponse(BaseModel):
    created: list[str]
    updated: list[str]
    unchanged: list[str]
    skipped: list[str]

"""Agent skills: the platform library and workspace-owned copies.

A skill is an Agent-Skills-style ``SKILL.md`` (frontmatter + markdown body)
plus optional text reference files. Library skills (``skill_library``) follow
the ``WorkflowTemplates`` precedent and have no ``organization_id``: platform
admins curate them and every workspace can read the published ones.
Selecting one copies it into ``skills``, which is organization-scoped.

Fork-owned module. ``api.db.models`` imports it at the bottom so the tables
are part of ``Base.metadata`` wherever the models are loaded (Alembic,
tests, the app).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.models import Base


class LibrarySkillStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class SkillStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class SkillLibraryModel(Base):  # type: ignore[valid-type,misc]
    """A platform skill. ``version`` counts published revisions (0 = never
    published); workspace copies record the version they were taken from."""

    __tablename__ = "skill_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    library_skill_uuid: Mapped[str] = mapped_column(
        String(36), unique=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(16),
        default=LibrarySkillStatus.DRAFT.value,
        server_default=LibrarySkillStatus.DRAFT.value,
    )
    category: Mapped[str | None] = mapped_column(String(64))
    # Optional Agent Skills frontmatter fields kept for export fidelity:
    # {"license": str, "compatibility": str, "metadata": {str: str}}.
    frontmatter_extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # SHA-256 of the seed folder (api/skills_library/<name>) this row was last
    # synced from; null for skills authored through the API.
    seed_hash: Mapped[str | None] = mapped_column(String(64))
    # Content fingerprint at the last publish: re-publishing unchanged content
    # (e.g. deprecate -> publish) does not bump the version.
    published_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'deprecated')",
            name="ck_skill_library_status",
        ),
    )


class SkillLibraryFileModel(Base):  # type: ignore[valid-type,misc]
    __tablename__ = "skill_library_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    library_skill_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("skill_library.library_skill_uuid", ondelete="CASCADE"),
    )
    path: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "library_skill_uuid", "path", name="uq_skill_library_files_skill_path"
        ),
    )


class SkillModel(Base):  # type: ignore[valid-type,misc]
    """A workspace skill: private, or a copy of a library skill."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_uuid: Mapped[str] = mapped_column(String(36), unique=True, default=_new_uuid)
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16),
        default=SkillStatus.ACTIVE.value,
        server_default=SkillStatus.ACTIVE.value,
    )
    # Tool UUIDs of this organization; null means no restriction.
    allowed_tool_uuids: Mapped[list[str] | None] = mapped_column(JSON)
    frontmatter_extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Fork tracking: null for a private skill.
    source_library_uuid: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("skill_library.library_skill_uuid", ondelete="SET NULL"),
    )
    source_version: Mapped[int | None] = mapped_column(Integer)
    is_modified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_skills_status"),
        # Names are unique per organization among non-archived skills, so
        # archiving a skill frees its name.
        Index(
            "uq_skills_org_name_active",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),
        Index("ix_skills_organization_id", "organization_id"),
        Index("ix_skills_source_library_uuid", "source_library_uuid"),
    )


class SkillFileModel(Base):  # type: ignore[valid-type,misc]
    __tablename__ = "skill_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_uuid: Mapped[str] = mapped_column(
        String(36), ForeignKey("skills.skill_uuid", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("skill_uuid", "path", name="uq_skill_files_skill_path"),
    )

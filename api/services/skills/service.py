"""Skill lifecycle: workspace skills (org-scoped) and the platform library.

Workspace rules:

- Every read and write is scoped by ``organization_id``.
- ``allowed_tool_uuids`` must name active tools of the same organization.
- Copy-on-select copies a *published* library skill's content into the
  workspace and records ``source_library_uuid``/``source_version``.
- Changing a copy's content (description, body, files, frontmatter extras)
  sets ``is_modified``; renaming it or changing its allowed tools does not,
  since those are workspace settings the library does not have.
- ``update_available``: the source is still published at a newer version.
- Applying a library update replaces the content (name and allowed tools are
  kept) and is refused for a modified copy unless forced.

Library rules: ``version`` counts published revisions. Publishing a draft or
deprecated skill bumps it; editing the content of a published skill bumps it
too, since the edit is live for new copies immediately.
"""

import difflib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from api.db.skill_client import (
    FrontmatterExtra,
    LibraryChanges,
    LibrarySeed,
    LibrarySkill,
    SeedSyncReport,
    SkillChanges,
    SkillContent,
    SkillFile,
    WorkspaceSkill,
    content_hash,
)
from api.db.skill_models import LibrarySkillStatus
from api.errors.skills import (
    LibrarySkillNotFoundError,
    SkillModifiedError,
    SkillNameConflictError,
    SkillNotFoundError,
    SkillStateError,
    SkillValidationError,
)
from api.services.skills import validation
from api.services.skills.archive import export_skill_zip, read_skill_upload
from api.services.skills.frontmatter import render_skill_md
from api.services.skills.ports import LibraryStore, ToolDirectory, WorkspaceSkillStore


@dataclass(frozen=True, slots=True)
class SkillEdit:
    """A partial update; ``None`` leaves a field unchanged. Allowed tools are
    applied only when ``set_allowed_tools`` is true (so they can be cleared)."""

    name: str | None = None
    description: str | None = None
    body_md: str | None = None
    files: tuple[SkillFile, ...] | None = None
    extra: FrontmatterExtra | None = None
    set_allowed_tools: bool = False
    allowed_tool_uuids: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class LibraryEdit:
    name: str | None = None
    description: str | None = None
    body_md: str | None = None
    files: tuple[SkillFile, ...] | None = None
    extra: FrontmatterExtra | None = None
    set_category: bool = False
    category: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryDiff:
    skill: WorkspaceSkill
    library: LibrarySkill
    # Unified diff, workspace copy (a/) -> latest library (b/); "" if equal.
    diff: str


@dataclass(frozen=True, slots=True)
class ImportedSkill:
    skill: WorkspaceSkill
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportedSkill:
    filename: str
    data: bytes


class SkillService:
    """Workspace skills of one organization per call."""

    def __init__(
        self,
        *,
        skills: WorkspaceSkillStore,
        library: LibraryStore,
        tools: ToolDirectory,
    ) -> None:
        self._skills = skills
        self._library = library
        self._tools = tools

    async def list_skills(
        self, organization_id: int, *, include_archived: bool = False
    ) -> list[WorkspaceSkill]:
        return await self._skills.list_workspace_skills(
            organization_id, include_archived=include_archived
        )

    async def get_skill(self, organization_id: int, skill_uuid: str) -> WorkspaceSkill:
        skill = await self._skills.get_workspace_skill(organization_id, skill_uuid)
        if skill is None:
            raise SkillNotFoundError()
        return skill

    async def create_skill(
        self,
        organization_id: int,
        *,
        created_by: int | None,
        content: SkillContent,
        allowed_tool_uuids: Sequence[str] | None = None,
    ) -> WorkspaceSkill:
        content = validation.validate_content(content)
        tools = await self._resolve_tools(organization_id, allowed_tool_uuids)
        return await self._create(
            organization_id, created_by=created_by, content=content, tools=tools
        )

    async def update_skill(
        self, organization_id: int, skill_uuid: str, edit: SkillEdit
    ) -> WorkspaceSkill:
        current = await self._active(organization_id, skill_uuid)
        old = current.content
        description = (
            validation.validate_description(edit.description)
            if edit.description is not None
            else None
        )
        body = (
            validation.validate_body(edit.body_md) if edit.body_md is not None else None
        )
        files = (
            validation.validate_files(edit.files) if edit.files is not None else None
        )
        extra = (
            validation.validate_extra(edit.extra) if edit.extra is not None else None
        )
        content_changed = (
            (description is not None and description != old.description)
            or (body is not None and body != old.body_md)
            or (files is not None and files != old.files)
            or (extra is not None and extra != old.extra)
        )
        changes = SkillChanges(
            name=validation.validate_name(edit.name) if edit.name is not None else None,
            description=description,
            body_md=body,
            files=files,
            extra=extra,
            set_allowed_tools=edit.set_allowed_tools,
            allowed_tool_uuids=(
                await self._resolve_tools(organization_id, edit.allowed_tool_uuids)
                if edit.set_allowed_tools
                else None
            ),
            is_modified=(
                True
                if content_changed and current.source_library_uuid is not None
                else None
            ),
        )
        return await self._update(organization_id, skill_uuid, changes)

    async def archive_skill(self, organization_id: int, skill_uuid: str) -> None:
        if not await self._skills.archive_workspace_skill(organization_id, skill_uuid):
            raise SkillNotFoundError()

    async def copy_from_library(
        self,
        organization_id: int,
        library_skill_uuid: str,
        *,
        created_by: int | None,
        name: str | None = None,
    ) -> WorkspaceSkill:
        library = await self._library.get_library_skill(library_skill_uuid)
        if library is None or library.status is not LibrarySkillStatus.PUBLISHED:
            raise LibrarySkillNotFoundError()
        content = library.content
        if name is not None:
            content = replace(content, name=validation.validate_name(name))
        return await self._create(
            organization_id,
            created_by=created_by,
            content=content,
            tools=None,
            source_library_uuid=library.library_skill_uuid,
            source_version=library.version,
        )

    async def library_diff(self, organization_id: int, skill_uuid: str) -> LibraryDiff:
        skill = await self.get_skill(organization_id, skill_uuid)
        library = await self._source(skill)
        return LibraryDiff(
            skill=skill,
            library=library,
            diff=_unified_diff(skill.content, library.content),
        )

    async def apply_library_update(
        self, organization_id: int, skill_uuid: str, *, force: bool = False
    ) -> WorkspaceSkill:
        skill = await self._active(organization_id, skill_uuid)
        library = await self._source(skill)
        if library.status is not LibrarySkillStatus.PUBLISHED:
            raise SkillStateError(
                "The library skill is no longer published; there is no update to apply"
            )
        if skill.is_modified and not force:
            raise SkillModifiedError()
        changes = SkillChanges(
            description=library.content.description,
            body_md=library.content.body_md,
            files=library.content.files,
            extra=library.content.extra,
            is_modified=False,
            source_version=library.version,
            # Re-checked under the row lock: an edit landing between the read
            # above and this write must not be overwritten.
            expect_unmodified=not force,
        )
        return await self._update(organization_id, skill_uuid, changes)

    async def import_skill(
        self, organization_id: int, *, created_by: int | None, data: bytes
    ) -> ImportedSkill:
        """Import a skill. ``allowed-tools`` entries that are not active tools
        of this workspace (e.g. Claude's ``Read``, or another workspace's
        UUIDs) are dropped with a warning: narrowing is always safe. If the
        key listed tools and none survive, the skill allows no tools (``()``),
        never "any tool" (``None``)."""
        document = read_skill_upload(data)
        warnings: list[str] = []
        tools: tuple[str, ...] | None = None
        if document.allowed_tools is not None:
            candidates = [
                str(uuid.UUID(t))
                for t in document.allowed_tools
                if validation.is_uuid(t)
            ]
            found = await self._tools.find_active_tool_uuids(
                organization_id, candidates
            )
            kept: list[str] = []
            dropped: list[str] = []
            for entry in document.allowed_tools:
                canonical = str(uuid.UUID(entry)) if validation.is_uuid(entry) else None
                if canonical is not None and canonical in found:
                    if canonical not in kept:
                        kept.append(canonical)
                else:
                    dropped.append(entry[:64])
            if dropped:
                warnings.append(
                    "Dropped allowed-tools entries that are not tools in this "
                    "workspace: " + ", ".join(dropped[:20])
                )
            tools = validation.normalize_tool_uuids(kept)
        skill = await self._create(
            organization_id,
            created_by=created_by,
            content=document.content,
            tools=tools,
        )
        return ImportedSkill(skill=skill, warnings=tuple(warnings))

    async def export_skill(
        self, organization_id: int, skill_uuid: str
    ) -> ExportedSkill:
        skill = await self.get_skill(organization_id, skill_uuid)
        data = export_skill_zip(skill.content, allowed_tools=skill.allowed_tool_uuids)
        return ExportedSkill(filename=f"{skill.content.name}.zip", data=data)

    # -- helpers ----------------------------------------------------------------

    async def _active(self, organization_id: int, skill_uuid: str) -> WorkspaceSkill:
        skill = await self._skills.get_workspace_skill(
            organization_id, skill_uuid, include_archived=False
        )
        if skill is None:
            raise SkillNotFoundError()
        return skill

    async def _source(self, skill: WorkspaceSkill) -> LibrarySkill:
        if skill.source_library_uuid is None:
            raise SkillStateError("This skill was not added from the library")
        library = await self._library.get_library_skill(skill.source_library_uuid)
        if library is None or library.status is LibrarySkillStatus.DRAFT:
            raise LibrarySkillNotFoundError()
        return library

    async def _resolve_tools(
        self, organization_id: int, tool_uuids: Sequence[str] | None
    ) -> tuple[str, ...] | None:
        if tool_uuids is None:
            return None
        normalized = validation.normalize_tool_uuids(tool_uuids)
        found = await self._tools.find_active_tool_uuids(organization_id, normalized)
        unknown = [u for u in normalized if u not in found]
        if unknown:
            raise SkillValidationError(
                "Unknown tools in allowed tools: "
                + ", ".join(u[:64] for u in unknown[:10])
                + ". Use the UUIDs of active tools in this workspace."
            )
        return normalized

    async def _create(
        self,
        organization_id: int,
        *,
        created_by: int | None,
        content: SkillContent,
        tools: tuple[str, ...] | None,
        source_library_uuid: str | None = None,
        source_version: int | None = None,
    ) -> WorkspaceSkill:
        try:
            return await self._skills.create_workspace_skill(
                organization_id=organization_id,
                created_by=created_by,
                content=content,
                allowed_tool_uuids=tools,
                source_library_uuid=source_library_uuid,
                source_version=source_version,
                max_active=validation.MAX_ACTIVE_SKILLS,
            )
        except SkillNameConflictError as exc:
            raise await self._with_suggestion(organization_id, exc.name) from None

    async def _update(
        self, organization_id: int, skill_uuid: str, changes: SkillChanges
    ) -> WorkspaceSkill:
        try:
            updated = await self._skills.update_workspace_skill(
                organization_id, skill_uuid, changes
            )
        except SkillNameConflictError as exc:
            raise await self._with_suggestion(organization_id, exc.name) from None
        if updated is None:
            raise SkillNotFoundError()
        return updated

    async def _with_suggestion(
        self, organization_id: int, name: str
    ) -> SkillNameConflictError:
        taken = await self._skills.list_active_skill_names(organization_id)
        return SkillNameConflictError(
            name, suggestion=validation.suggest_name(name, taken)
        )


class LibraryService:
    """The platform skill library. Callers enforce who may write."""

    def __init__(self, *, library: LibraryStore) -> None:
        self._library = library

    async def list_skills(self, *, include_unpublished: bool) -> list[LibrarySkill]:
        statuses = None if include_unpublished else (LibrarySkillStatus.PUBLISHED,)
        return await self._library.list_library_skills(statuses=statuses)

    async def get_skill(
        self, library_skill_uuid: str, *, include_unpublished: bool
    ) -> LibrarySkill:
        skill = await self._library.get_library_skill(library_skill_uuid)
        if skill is None or (
            not include_unpublished and skill.status is not LibrarySkillStatus.PUBLISHED
        ):
            raise LibrarySkillNotFoundError()
        return skill

    async def create_skill(
        self, content: SkillContent, *, category: str | None = None
    ) -> LibrarySkill:
        return await self._library.create_library_skill(
            validation.validate_content(content),
            category=validation.validate_category(category),
        )

    async def update_skill(
        self, library_skill_uuid: str, edit: LibraryEdit
    ) -> LibrarySkill:
        current = await self.get_skill(library_skill_uuid, include_unpublished=True)
        old = current.content
        description = (
            validation.validate_description(edit.description)
            if edit.description is not None
            else None
        )
        body = (
            validation.validate_body(edit.body_md) if edit.body_md is not None else None
        )
        files = (
            validation.validate_files(edit.files) if edit.files is not None else None
        )
        extra = (
            validation.validate_extra(edit.extra) if edit.extra is not None else None
        )
        content_changed = (
            (description is not None and description != old.description)
            or (body is not None and body != old.body_md)
            or (files is not None and files != old.files)
            or (extra is not None and extra != old.extra)
        )
        # Editing a published skill's content is live for new copies, so it
        # is a new published version.
        republish = content_changed and current.status is LibrarySkillStatus.PUBLISHED
        published_hash = (
            content_hash(
                replace(
                    old,
                    description=description or old.description,
                    body_md=body or old.body_md,
                    files=files if files is not None else old.files,
                    extra=extra if extra is not None else old.extra,
                )
            )
            if republish
            else None
        )
        return await self._apply(
            library_skill_uuid,
            LibraryChanges(
                name=validation.validate_name(edit.name)
                if edit.name is not None
                else None,
                description=description,
                body_md=body,
                files=files,
                extra=extra,
                set_category=edit.set_category,
                category=(
                    validation.validate_category(edit.category)
                    if edit.set_category
                    else None
                ),
                bump_version=republish,
                published_hash=published_hash,
            ),
        )

    async def publish(self, library_skill_uuid: str) -> LibrarySkill:
        """Publish. The version is bumped only when the content differs from
        what was last published, so deprecate -> publish of unchanged content
        does not make every workspace copy report an update."""
        current = await self.get_skill(library_skill_uuid, include_unpublished=True)
        if current.status is LibrarySkillStatus.PUBLISHED:
            return current
        digest = content_hash(current.content)
        changed = digest != current.published_hash
        return await self._apply(
            library_skill_uuid,
            LibraryChanges(
                status=LibrarySkillStatus.PUBLISHED,
                bump_version=changed,
                published_hash=digest if changed else None,
            ),
        )

    async def deprecate(self, library_skill_uuid: str) -> LibrarySkill:
        await self.get_skill(library_skill_uuid, include_unpublished=True)
        return await self._apply(
            library_skill_uuid, LibraryChanges(status=LibrarySkillStatus.DEPRECATED)
        )

    async def delete_skill(self, library_skill_uuid: str) -> None:
        if not await self._library.delete_library_skill(library_skill_uuid):
            raise LibrarySkillNotFoundError()

    async def sync_seeds(self, seeds: Sequence[LibrarySeed]) -> SeedSyncReport:
        return await self._library.sync_library_seeds(seeds)

    async def _apply(
        self, library_skill_uuid: str, changes: LibraryChanges
    ) -> LibrarySkill:
        updated = await self._library.update_library_skill(library_skill_uuid, changes)
        if updated is None:
            raise LibrarySkillNotFoundError()
        return updated


def _unified_diff(current: SkillContent, latest: SkillContent) -> str:
    """Diff of SKILL.md and every file, workspace copy -> latest library.

    Both sides render SKILL.md with the workspace name, so a library rename
    (which an update does not apply) does not show up as a change.
    """
    left = {"SKILL.md": render_skill_md(current)}
    left.update({f.path: f.content for f in current.files})
    right = {"SKILL.md": render_skill_md(replace(latest, name=current.name))}
    right.update({f.path: f.content for f in latest.files})
    chunks: list[str] = []
    for path in ["SKILL.md", *sorted((left.keys() | right.keys()) - {"SKILL.md"})]:
        before, after = left.get(path), right.get(path)
        chunks.extend(
            difflib.unified_diff(
                _lines(before),
                _lines(after),
                fromfile=f"a/{path}" if before is not None else "/dev/null",
                tofile=f"b/{path}" if after is not None else "/dev/null",
            )
        )
    return "".join(chunks)


def _lines(text: str | None) -> list[str]:
    if text is None:
        return []
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines

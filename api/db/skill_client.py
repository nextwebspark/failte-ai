"""Data access for agent skills: the platform library and workspace skills.

Workspace methods take ``organization_id`` and filter by it in the query;
library methods are platform-wide (the library has no organization).
Content is validated by ``api.services.skills`` before it reaches here.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.base_client import BaseDBClient
from api.db.models import ToolModel
from api.db.skill_models import (
    LibrarySkillStatus,
    SkillFileModel,
    SkillLibraryFileModel,
    SkillLibraryModel,
    SkillModel,
    SkillStatus,
)
from api.enums import ToolStatus
from api.errors.skills import SkillNameConflictError

_SEED_LOCK_KEY = "skill_library:seed_sync"


@dataclass(frozen=True, slots=True)
class SkillFile:
    path: str
    content: str


@dataclass(frozen=True, slots=True)
class FrontmatterExtra:
    """Optional Agent Skills frontmatter fields, kept so exports round-trip."""

    license: str | None = None
    compatibility: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return self.license is None and self.compatibility is None and not self.metadata

    def to_json(self) -> dict[str, Any] | None:
        if self.is_empty():
            return None
        data: dict[str, Any] = {}
        if self.license is not None:
            data["license"] = self.license
        if self.compatibility is not None:
            data["compatibility"] = self.compatibility
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any] | None) -> "FrontmatterExtra":
        if not data:
            return cls()
        license_ = data.get("license")
        compatibility = data.get("compatibility")
        metadata = data.get("metadata") or {}
        return cls(
            license=str(license_) if license_ is not None else None,
            compatibility=str(compatibility) if compatibility is not None else None,
            metadata={str(k): str(v) for k, v in dict(metadata).items()},
        )


@dataclass(frozen=True, slots=True)
class SkillContent:
    """The portable part of a skill: what ``SKILL.md`` plus files hold."""

    name: str
    description: str
    body_md: str
    files: tuple[SkillFile, ...] = ()
    extra: FrontmatterExtra = field(default_factory=FrontmatterExtra)


@dataclass(frozen=True, slots=True)
class WorkspaceSkill:
    skill_uuid: str
    organization_id: int
    content: SkillContent
    status: SkillStatus
    allowed_tool_uuids: tuple[str, ...] | None
    source_library_uuid: str | None
    source_version: int | None
    is_modified: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    # Version and status of the source library skill, when it still exists.
    library_version: int | None = None
    library_status: LibrarySkillStatus | None = None
    # False when the record was loaded without its files (listings).
    files_loaded: bool = True

    @property
    def update_available(self) -> bool:
        return (
            self.source_library_uuid is not None
            and self.source_version is not None
            and self.library_status is LibrarySkillStatus.PUBLISHED
            and self.library_version is not None
            and self.library_version > self.source_version
        )


@dataclass(frozen=True, slots=True)
class LibrarySkill:
    library_skill_uuid: str
    content: SkillContent
    version: int
    status: LibrarySkillStatus
    category: str | None
    is_seeded: bool
    created_at: datetime
    updated_at: datetime
    files_loaded: bool = True


@dataclass(frozen=True, slots=True)
class SkillChanges:
    """Fields to change on a workspace skill; ``None`` leaves a field as is.

    ``allowed_tool_uuids`` is applied only when ``set_allowed_tools`` is true
    (so it can be cleared to ``None``).
    """

    name: str | None = None
    description: str | None = None
    body_md: str | None = None
    files: tuple[SkillFile, ...] | None = None
    extra: FrontmatterExtra | None = None
    set_allowed_tools: bool = False
    allowed_tool_uuids: tuple[str, ...] | None = None
    is_modified: bool | None = None
    source_version: int | None = None


@dataclass(frozen=True, slots=True)
class LibraryChanges:
    name: str | None = None
    description: str | None = None
    body_md: str | None = None
    files: tuple[SkillFile, ...] | None = None
    extra: FrontmatterExtra | None = None
    set_category: bool = False
    category: str | None = None
    status: LibrarySkillStatus | None = None
    bump_version: bool = False


@dataclass(frozen=True, slots=True)
class LibrarySeed:
    content: SkillContent
    category: str | None
    seed_hash: str


@dataclass(frozen=True, slots=True)
class SeedSyncReport:
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    # Names held by an API-authored library skill; never overwritten.
    skipped: tuple[str, ...] = ()


def _files(
    rows: Iterable[SkillFileModel | SkillLibraryFileModel],
) -> tuple[SkillFile, ...]:
    return tuple(
        SkillFile(path=r.path, content=r.content)
        for r in sorted(rows, key=lambda r: r.path)
    )


def _to_library(
    row: SkillLibraryModel, files: tuple[SkillFile, ...] | None
) -> LibrarySkill:
    return LibrarySkill(
        library_skill_uuid=row.library_skill_uuid,
        content=SkillContent(
            name=row.name,
            description=row.description,
            body_md=row.body_md,
            files=files or (),
            extra=FrontmatterExtra.from_json(row.frontmatter_extra),
        ),
        version=row.version,
        status=LibrarySkillStatus(row.status),
        category=row.category,
        is_seeded=row.seed_hash is not None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        files_loaded=files is not None,
    )


def _to_workspace(
    row: SkillModel,
    files: tuple[SkillFile, ...] | None,
    library: tuple[int, str] | None,
) -> WorkspaceSkill:
    return WorkspaceSkill(
        skill_uuid=row.skill_uuid,
        organization_id=row.organization_id,
        content=SkillContent(
            name=row.name,
            description=row.description,
            body_md=row.body_md,
            files=files or (),
            extra=FrontmatterExtra.from_json(row.frontmatter_extra),
        ),
        status=SkillStatus(row.status),
        allowed_tool_uuids=(
            tuple(row.allowed_tool_uuids)
            if row.allowed_tool_uuids is not None
            else None
        ),
        source_library_uuid=row.source_library_uuid,
        source_version=row.source_version,
        is_modified=row.is_modified,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        library_version=library[0] if library else None,
        library_status=LibrarySkillStatus(library[1]) if library else None,
        files_loaded=files is not None,
    )


def _is_name_conflict(exc: IntegrityError) -> bool:
    text = str(exc.orig)
    return "uq_skills_org_name_active" in text or "skill_library_name_key" in text


class SkillClient(BaseDBClient):
    # -- workspace skills ------------------------------------------------------

    async def _workspace_row(
        self,
        session: AsyncSession,
        organization_id: int,
        skill_uuid: str,
        *,
        include_archived: bool,
        for_update: bool = False,
    ) -> SkillModel | None:
        query = select(SkillModel).where(
            SkillModel.organization_id == organization_id,
            SkillModel.skill_uuid == skill_uuid,
        )
        if not include_archived:
            query = query.where(SkillModel.status != SkillStatus.ARCHIVED.value)
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _load_workspace(
        self, session: AsyncSession, row: SkillModel, *, with_files: bool
    ) -> WorkspaceSkill:
        files: tuple[SkillFile, ...] | None = None
        if with_files:
            result = await session.execute(
                select(SkillFileModel).where(
                    SkillFileModel.skill_uuid == row.skill_uuid
                )
            )
            files = _files(result.scalars().all())
        library: tuple[int, str] | None = None
        if row.source_library_uuid is not None:
            lib = await session.execute(
                select(SkillLibraryModel.version, SkillLibraryModel.status).where(
                    SkillLibraryModel.library_skill_uuid == row.source_library_uuid
                )
            )
            found = lib.one_or_none()
            if found is not None:
                library = (int(found[0]), str(found[1]))
        return _to_workspace(row, files, library)

    async def list_workspace_skills(
        self, organization_id: int, *, include_archived: bool = False
    ) -> list[WorkspaceSkill]:
        """Skills of the organization, by name, without their files."""
        async with self.async_session() as session:
            query = (
                select(SkillModel, SkillLibraryModel.version, SkillLibraryModel.status)
                .outerjoin(
                    SkillLibraryModel,
                    SkillLibraryModel.library_skill_uuid
                    == SkillModel.source_library_uuid,
                )
                .where(SkillModel.organization_id == organization_id)
                .order_by(SkillModel.name, SkillModel.id)
            )
            if not include_archived:
                query = query.where(SkillModel.status != SkillStatus.ARCHIVED.value)
            result = await session.execute(query)
            return [
                _to_workspace(
                    row,
                    None,
                    (int(version), str(status)) if version is not None else None,
                )
                for row, version, status in result.all()
            ]

    async def get_workspace_skill(
        self,
        organization_id: int,
        skill_uuid: str,
        *,
        include_archived: bool = True,
    ) -> WorkspaceSkill | None:
        async with self.async_session() as session:
            row = await self._workspace_row(
                session,
                organization_id,
                skill_uuid,
                include_archived=include_archived,
            )
            if row is None:
                return None
            return await self._load_workspace(session, row, with_files=True)

    async def list_active_skill_names(self, organization_id: int) -> set[str]:
        async with self.async_session() as session:
            result = await session.execute(
                select(SkillModel.name).where(
                    SkillModel.organization_id == organization_id,
                    SkillModel.status != SkillStatus.ARCHIVED.value,
                )
            )
            return set(result.scalars().all())

    async def create_workspace_skill(
        self,
        *,
        organization_id: int,
        created_by: int | None,
        content: SkillContent,
        allowed_tool_uuids: tuple[str, ...] | None,
        source_library_uuid: str | None = None,
        source_version: int | None = None,
    ) -> WorkspaceSkill:
        async with self.async_session() as session:
            row = SkillModel(
                organization_id=organization_id,
                name=content.name,
                description=content.description,
                body_md=content.body_md,
                status=SkillStatus.ACTIVE.value,
                allowed_tool_uuids=(
                    list(allowed_tool_uuids) if allowed_tool_uuids is not None else None
                ),
                frontmatter_extra=content.extra.to_json(),
                source_library_uuid=source_library_uuid,
                source_version=source_version,
                is_modified=False,
                created_by=created_by,
            )
            session.add(row)
            try:
                async with session.begin_nested():
                    await session.flush()
            except IntegrityError as exc:
                if _is_name_conflict(exc):
                    raise SkillNameConflictError(content.name) from None
                raise
            session.add_all(
                SkillFileModel(
                    skill_uuid=row.skill_uuid, path=f.path, content=f.content
                )
                for f in content.files
            )
            await session.commit()
            await session.refresh(row)
            return await self._load_workspace(session, row, with_files=True)

    async def update_workspace_skill(
        self, organization_id: int, skill_uuid: str, changes: SkillChanges
    ) -> WorkspaceSkill | None:
        """Apply ``changes`` to an active skill; ``None`` if there is none."""
        async with self.async_session() as session:
            row = await self._workspace_row(
                session,
                organization_id,
                skill_uuid,
                include_archived=False,
                for_update=True,
            )
            if row is None:
                return None
            if changes.name is not None:
                row.name = changes.name
            if changes.description is not None:
                row.description = changes.description
            if changes.body_md is not None:
                row.body_md = changes.body_md
            if changes.extra is not None:
                row.frontmatter_extra = changes.extra.to_json()
            if changes.set_allowed_tools:
                row.allowed_tool_uuids = (
                    list(changes.allowed_tool_uuids)
                    if changes.allowed_tool_uuids is not None
                    else None
                )
            if changes.is_modified is not None:
                row.is_modified = changes.is_modified
            if changes.source_version is not None:
                row.source_version = changes.source_version
            if changes.files is not None:
                await session.execute(
                    delete(SkillFileModel).where(
                        SkillFileModel.skill_uuid == row.skill_uuid
                    )
                )
                session.add_all(
                    SkillFileModel(
                        skill_uuid=row.skill_uuid, path=f.path, content=f.content
                    )
                    for f in changes.files
                )
            try:
                async with session.begin_nested():
                    await session.flush()
            except IntegrityError as exc:
                if _is_name_conflict(exc):
                    raise SkillNameConflictError(changes.name or row.name) from None
                raise
            await session.commit()
            await session.refresh(row)
            return await self._load_workspace(session, row, with_files=True)

    async def archive_workspace_skill(
        self, organization_id: int, skill_uuid: str
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                update(SkillModel)
                .where(
                    SkillModel.organization_id == organization_id,
                    SkillModel.skill_uuid == skill_uuid,
                    SkillModel.status != SkillStatus.ARCHIVED.value,
                )
                .values(status=SkillStatus.ARCHIVED.value)
                .returning(SkillModel.id)
            )
            archived = result.first() is not None
            await session.commit()
            return archived

    async def find_active_tool_uuids(
        self, organization_id: int, tool_uuids: Collection[str]
    ) -> set[str]:
        """The subset of ``tool_uuids`` that are active tools of the org."""
        if not tool_uuids:
            return set()
        async with self.async_session() as session:
            result = await session.execute(
                select(ToolModel.tool_uuid).where(
                    ToolModel.organization_id == organization_id,
                    ToolModel.tool_uuid.in_(list(tool_uuids)),
                    ToolModel.status == ToolStatus.ACTIVE.value,
                )
            )
            return {str(u) for u in result.scalars().all()}

    # -- library ---------------------------------------------------------------

    async def _library_row(
        self, session: AsyncSession, library_skill_uuid: str, *, for_update: bool
    ) -> SkillLibraryModel | None:
        query = select(SkillLibraryModel).where(
            SkillLibraryModel.library_skill_uuid == library_skill_uuid
        )
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _load_library(
        self, session: AsyncSession, row: SkillLibraryModel
    ) -> LibrarySkill:
        result = await session.execute(
            select(SkillLibraryFileModel).where(
                SkillLibraryFileModel.library_skill_uuid == row.library_skill_uuid
            )
        )
        return _to_library(row, _files(result.scalars().all()))

    async def list_library_skills(
        self, *, statuses: Collection[LibrarySkillStatus] | None = None
    ) -> list[LibrarySkill]:
        """Library skills by name, without their files."""
        async with self.async_session() as session:
            query = select(SkillLibraryModel).order_by(SkillLibraryModel.name)
            if statuses is not None:
                query = query.where(
                    SkillLibraryModel.status.in_([s.value for s in statuses])
                )
            result = await session.execute(query)
            return [_to_library(row, None) for row in result.scalars().all()]

    async def get_library_skill(self, library_skill_uuid: str) -> LibrarySkill | None:
        async with self.async_session() as session:
            row = await self._library_row(session, library_skill_uuid, for_update=False)
            if row is None:
                return None
            return await self._load_library(session, row)

    async def create_library_skill(
        self, content: SkillContent, *, category: str | None
    ) -> LibrarySkill:
        async with self.async_session() as session:
            row = self._new_library_row(content, category=category)
            session.add(row)
            try:
                async with session.begin_nested():
                    await session.flush()
            except IntegrityError as exc:
                if _is_name_conflict(exc):
                    raise SkillNameConflictError(content.name) from None
                raise
            self._add_library_files(session, row.library_skill_uuid, content.files)
            await session.commit()
            await session.refresh(row)
            return await self._load_library(session, row)

    @staticmethod
    def _new_library_row(
        content: SkillContent,
        *,
        category: str | None,
        status: LibrarySkillStatus = LibrarySkillStatus.DRAFT,
        version: int = 0,
        seed_hash: str | None = None,
    ) -> SkillLibraryModel:
        return SkillLibraryModel(
            name=content.name,
            description=content.description,
            body_md=content.body_md,
            version=version,
            status=status.value,
            category=category,
            frontmatter_extra=content.extra.to_json(),
            seed_hash=seed_hash,
        )

    @staticmethod
    def _add_library_files(
        session: AsyncSession, library_skill_uuid: str, files: Sequence[SkillFile]
    ) -> None:
        session.add_all(
            SkillLibraryFileModel(
                library_skill_uuid=library_skill_uuid, path=f.path, content=f.content
            )
            for f in files
        )

    async def update_library_skill(
        self, library_skill_uuid: str, changes: LibraryChanges
    ) -> LibrarySkill | None:
        async with self.async_session() as session:
            row = await self._library_row(session, library_skill_uuid, for_update=True)
            if row is None:
                return None
            await self._apply_library_changes(session, row, changes)
            try:
                async with session.begin_nested():
                    await session.flush()
            except IntegrityError as exc:
                if _is_name_conflict(exc):
                    raise SkillNameConflictError(changes.name or row.name) from None
                raise
            await session.commit()
            await session.refresh(row)
            return await self._load_library(session, row)

    @staticmethod
    async def _apply_library_changes(
        session: AsyncSession, row: SkillLibraryModel, changes: LibraryChanges
    ) -> None:
        if changes.name is not None:
            row.name = changes.name
        if changes.description is not None:
            row.description = changes.description
        if changes.body_md is not None:
            row.body_md = changes.body_md
        if changes.extra is not None:
            row.frontmatter_extra = changes.extra.to_json()
        if changes.set_category:
            row.category = changes.category
        if changes.status is not None:
            row.status = changes.status.value
        if changes.bump_version:
            row.version = row.version + 1
        if changes.files is not None:
            await session.execute(
                delete(SkillLibraryFileModel).where(
                    SkillLibraryFileModel.library_skill_uuid == row.library_skill_uuid
                )
            )
            SkillClient._add_library_files(
                session, row.library_skill_uuid, changes.files
            )

    async def delete_library_skill(self, library_skill_uuid: str) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(SkillLibraryModel)
                .where(SkillLibraryModel.library_skill_uuid == library_skill_uuid)
                .returning(SkillLibraryModel.id)
            )
            deleted = result.first() is not None
            await session.commit()
            return deleted

    async def sync_library_seeds(self, seeds: Sequence[LibrarySeed]) -> SeedSyncReport:
        """Upsert seed skills by name in one transaction.

        A seed whose hash matches the row's ``seed_hash`` is left alone, so
        reruns are no-ops and edits made through the API survive until the
        seed folder itself changes. A changed seed replaces the content and,
        if the skill is published, bumps its version. New seeds are created
        published at version 1. A name held by an API-authored skill (no
        ``seed_hash``) is skipped. Concurrent syncs (several API workers
        starting at once) are serialized by an advisory lock.
        """
        created: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        skipped: list[str] = []
        async with self.async_session() as session:
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(func.hashtextextended(_SEED_LOCK_KEY, 0))
                )
            )
            for seed in seeds:
                name = seed.content.name
                result = await session.execute(
                    select(SkillLibraryModel)
                    .where(SkillLibraryModel.name == name)
                    .with_for_update()
                )
                row = result.scalar_one_or_none()
                if row is None:
                    row = self._new_library_row(
                        seed.content,
                        category=seed.category,
                        status=LibrarySkillStatus.PUBLISHED,
                        version=1,
                        seed_hash=seed.seed_hash,
                    )
                    session.add(row)
                    await session.flush()
                    self._add_library_files(
                        session, row.library_skill_uuid, seed.content.files
                    )
                    created.append(name)
                    continue
                if row.seed_hash is None:
                    skipped.append(name)
                    continue
                if row.seed_hash == seed.seed_hash:
                    unchanged.append(name)
                    continue
                await self._apply_library_changes(
                    session,
                    row,
                    LibraryChanges(
                        description=seed.content.description,
                        body_md=seed.content.body_md,
                        files=seed.content.files,
                        extra=seed.content.extra,
                        set_category=True,
                        category=seed.category,
                        bump_version=row.status == LibrarySkillStatus.PUBLISHED.value,
                    ),
                )
                row.seed_hash = seed.seed_hash
                updated.append(name)
            await session.commit()
        return SeedSyncReport(
            created=tuple(created),
            updated=tuple(updated),
            unchanged=tuple(unchanged),
            skipped=tuple(skipped),
        )

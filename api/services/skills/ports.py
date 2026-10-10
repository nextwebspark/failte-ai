"""Narrow storage interfaces the skill services depend on.

``api.db.db_client`` satisfies them structurally; tests may pass fakes.
"""

from collections.abc import Collection, Sequence
from typing import Protocol

from api.db.skill_client import (
    LibraryChanges,
    LibrarySeed,
    LibrarySkill,
    SeedSyncReport,
    SkillChanges,
    SkillContent,
    WorkspaceSkill,
)
from api.db.skill_models import LibrarySkillStatus


class WorkspaceSkillStore(Protocol):
    async def list_workspace_skills(
        self, organization_id: int, *, include_archived: bool = False
    ) -> list[WorkspaceSkill]: ...

    async def get_workspace_skill(
        self, organization_id: int, skill_uuid: str, *, include_archived: bool = True
    ) -> WorkspaceSkill | None: ...

    async def list_active_skill_names(self, organization_id: int) -> set[str]: ...

    async def create_workspace_skill(
        self,
        *,
        organization_id: int,
        created_by: int | None,
        content: SkillContent,
        allowed_tool_uuids: tuple[str, ...] | None,
        source_library_uuid: str | None = None,
        source_version: int | None = None,
    ) -> WorkspaceSkill: ...

    async def update_workspace_skill(
        self, organization_id: int, skill_uuid: str, changes: SkillChanges
    ) -> WorkspaceSkill | None: ...

    async def archive_workspace_skill(
        self, organization_id: int, skill_uuid: str
    ) -> bool: ...


class LibraryStore(Protocol):
    async def list_library_skills(
        self, *, statuses: Collection[LibrarySkillStatus] | None = None
    ) -> list[LibrarySkill]: ...

    async def get_library_skill(
        self, library_skill_uuid: str
    ) -> LibrarySkill | None: ...

    async def create_library_skill(
        self, content: SkillContent, *, category: str | None
    ) -> LibrarySkill: ...

    async def update_library_skill(
        self, library_skill_uuid: str, changes: LibraryChanges
    ) -> LibrarySkill | None: ...

    async def delete_library_skill(self, library_skill_uuid: str) -> bool: ...

    async def sync_library_seeds(
        self, seeds: Sequence[LibrarySeed]
    ) -> SeedSyncReport: ...


class ToolDirectory(Protocol):
    async def find_active_tool_uuids(
        self, organization_id: int, tool_uuids: Collection[str]
    ) -> set[str]: ...


class RuntimeSkillStore(Protocol):
    async def list_runtime_skills(
        self, organization_id: int
    ) -> list[WorkspaceSkill]: ...


class SkillDirectory(Protocol):
    async def find_active_skill_uuids(
        self, organization_id: int, skill_uuids: Collection[str]
    ) -> set[str]: ...

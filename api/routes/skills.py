"""Agent skills: workspace skills (``/skills``) and the platform library
(``/skill-library``).

Workspace skills are agent configuration, so they reuse the agent
permissions: reads need ``AGENTS_READ`` (every role), writes, copying from
the library, import and archive need ``AGENTS_WRITE`` (developer, admin).
Library reads need ``AGENTS_READ`` and see published skills only (platform
admins also see drafts and deprecated ones); library writes need a platform
admin (``is_superuser``).

Accepted limitation: library reads go through the org-membership dependency,
so a platform admin needs a selected organization to browse the library
(every real admin has one). Library writes need no organization.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from api.db.models import UserModel
from api.schemas.skills import (
    ApplyLibraryUpdateRequest,
    CopyLibrarySkillRequest,
    CreateLibrarySkillRequest,
    CreateSkillRequest,
    LibraryDiffResponse,
    LibrarySkillListResponse,
    LibrarySkillResponse,
    LibrarySkillSummaryResponse,
    SeedSyncResponse,
    SkillImportResponse,
    SkillListResponse,
    SkillResponse,
    SkillSummaryResponse,
    UpdateLibrarySkillRequest,
    UpdateSkillRequest,
)
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.auth.platform_admin import require_platform_admin
from api.services.skills import (
    LibraryEdit,
    LibraryService,
    SkillEdit,
    SkillService,
    get_library_service,
    get_skill_service,
    sync_seed_library,
)
from api.services.skills.validation import DEFAULT_LIMITS

router = APIRouter(prefix="/skills", tags=["skills"])
library_router = APIRouter(prefix="/skill-library", tags=["skill-library"])

Skills = Annotated[SkillService, Depends(get_skill_service)]
Library = Annotated[LibraryService, Depends(get_library_service)]
Reader = Annotated[OrgMembership, Depends(require_permission(Permission.AGENTS_READ))]
Writer = Annotated[OrgMembership, Depends(require_permission(Permission.AGENTS_WRITE))]
PlatformAdmin = Annotated[UserModel, Depends(require_platform_admin)]


# -- workspace skills ------------------------------------------------------------


@router.get("")
async def list_skills(
    membership: Reader,
    skills: Skills,
    include_archived: Annotated[bool, Query()] = False,
) -> SkillListResponse:
    """This workspace's skills, without bodies and files."""
    found = await skills.list_skills(
        membership.organization_id, include_archived=include_archived
    )
    return SkillListResponse(skills=[SkillSummaryResponse.from_skill(s) for s in found])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: CreateSkillRequest, membership: Writer, skills: Skills
) -> SkillResponse:
    """Create a private workspace skill."""
    skill = await skills.create_skill(
        membership.organization_id,
        created_by=membership.user.id,
        content=request.to_content(),
        allowed_tool_uuids=request.allowed_tool_uuids,
    )
    return SkillResponse.from_skill(skill)


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_skill(
    membership: Writer,
    skills: Skills,
    file: Annotated[UploadFile, File(description="A skill .zip or a SKILL.md")],
) -> SkillImportResponse:
    """Import a skill folder (``.zip``, standard layout) or a single
    ``SKILL.md``. ``allowed-tools`` entries that are not tool UUIDs of this
    workspace are dropped and reported in ``warnings``."""
    data = await file.read(DEFAULT_LIMITS.max_archive_bytes + 1)
    result = await skills.import_skill(
        membership.organization_id, created_by=membership.user.id, data=data
    )
    return SkillImportResponse(
        **SkillResponse.from_skill(result.skill).model_dump(),
        warnings=list(result.warnings),
    )


@router.post("/from-library/{library_skill_uuid}", status_code=status.HTTP_201_CREATED)
async def copy_library_skill(
    library_skill_uuid: str,
    membership: Writer,
    skills: Skills,
    request: CopyLibrarySkillRequest | None = None,
) -> SkillResponse:
    """Copy a published library skill into this workspace. A name already in
    use returns 409 with ``suggested_name``."""
    skill = await skills.copy_from_library(
        membership.organization_id,
        library_skill_uuid,
        created_by=membership.user.id,
        name=request.name if request else None,
    )
    return SkillResponse.from_skill(skill)


@router.get("/{skill_uuid}")
async def get_skill(
    skill_uuid: str, membership: Reader, skills: Skills
) -> SkillResponse:
    return SkillResponse.from_skill(
        await skills.get_skill(membership.organization_id, skill_uuid)
    )


@router.patch("/{skill_uuid}")
async def update_skill(
    skill_uuid: str, request: UpdateSkillRequest, membership: Writer, skills: Skills
) -> SkillResponse:
    """Edit a skill. Editing the content of a library copy marks it modified."""
    edit = SkillEdit(
        name=request.name,
        description=request.description,
        body_md=request.body_md,
        files=(
            tuple(f.to_file() for f in request.files)
            if request.files is not None
            else None
        ),
        extra=request.frontmatter_extra.to_extra()
        if request.frontmatter_extra
        else None,
        set_allowed_tools="allowed_tool_uuids" in request.model_fields_set,
        allowed_tool_uuids=(
            tuple(request.allowed_tool_uuids)
            if request.allowed_tool_uuids is not None
            else None
        ),
    )
    skill = await skills.update_skill(membership.organization_id, skill_uuid, edit)
    return SkillResponse.from_skill(skill)


@router.delete("/{skill_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_skill(skill_uuid: str, membership: Writer, skills: Skills) -> None:
    """Archive a skill; its name becomes free for a new skill."""
    await skills.archive_skill(membership.organization_id, skill_uuid)


@router.get("/{skill_uuid}/library-diff")
async def get_library_diff(
    skill_uuid: str, membership: Reader, skills: Skills
) -> LibraryDiffResponse:
    """Compare a library copy with the latest library version."""
    result = await skills.library_diff(membership.organization_id, skill_uuid)
    return LibraryDiffResponse(
        skill_uuid=result.skill.skill_uuid,
        library_skill_uuid=result.library.library_skill_uuid,
        source_version=result.skill.source_version,
        latest_version=result.library.version,
        library_status=result.library.status,
        is_modified=result.skill.is_modified,
        update_available=result.skill.update_available,
        diff=result.diff,
    )


@router.post("/{skill_uuid}/apply-library-update")
async def apply_library_update(
    skill_uuid: str,
    request: ApplyLibraryUpdateRequest,
    membership: Writer,
    skills: Skills,
) -> SkillResponse:
    """Replace a copy's content with the latest library version. Refused
    (409) for a modified copy unless ``force`` is true."""
    skill = await skills.apply_library_update(
        membership.organization_id, skill_uuid, force=request.force
    )
    return SkillResponse.from_skill(skill)


@router.get(
    "/{skill_uuid}/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_skill(skill_uuid: str, membership: Reader, skills: Skills) -> Response:
    """Download the skill as ``<name>.zip`` (``<name>/SKILL.md`` + files)."""
    exported = await skills.export_skill(membership.organization_id, skill_uuid)
    return Response(
        content=exported.data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )


# -- platform library ---------------------------------------------------------------


@library_router.get("")
async def list_library_skills(
    membership: Reader, library: Library
) -> LibrarySkillListResponse:
    """Published library skills (platform admins see every status)."""
    found = await library.list_skills(
        include_unpublished=bool(membership.user.is_superuser)
    )
    return LibrarySkillListResponse(
        skills=[LibrarySkillSummaryResponse.from_skill(s) for s in found]
    )


@library_router.get("/{library_skill_uuid}")
async def get_library_skill(
    library_skill_uuid: str, membership: Reader, library: Library
) -> LibrarySkillResponse:
    skill = await library.get_skill(
        library_skill_uuid, include_unpublished=bool(membership.user.is_superuser)
    )
    return LibrarySkillResponse.from_skill(skill)


@library_router.post("", status_code=status.HTTP_201_CREATED)
async def create_library_skill(
    request: CreateLibrarySkillRequest, _admin: PlatformAdmin, library: Library
) -> LibrarySkillResponse:
    """Create a draft library skill (platform admin)."""
    skill = await library.create_skill(request.to_content(), category=request.category)
    return LibrarySkillResponse.from_skill(skill)


@library_router.post("/sync-seeds")
async def sync_library_seeds(_admin: PlatformAdmin) -> SeedSyncResponse:
    """Sync the seed skills shipped in ``api/skills_library`` (platform admin;
    also runs at startup)."""
    report = await sync_seed_library()
    return SeedSyncResponse(
        created=list(report.created),
        updated=list(report.updated),
        unchanged=list(report.unchanged),
        skipped=list(report.skipped),
    )


@library_router.patch("/{library_skill_uuid}")
async def update_library_skill(
    library_skill_uuid: str,
    request: UpdateLibrarySkillRequest,
    _admin: PlatformAdmin,
    library: Library,
) -> LibrarySkillResponse:
    edit = LibraryEdit(
        name=request.name,
        description=request.description,
        body_md=request.body_md,
        files=(
            tuple(f.to_file() for f in request.files)
            if request.files is not None
            else None
        ),
        extra=request.frontmatter_extra.to_extra()
        if request.frontmatter_extra
        else None,
        set_category="category" in request.model_fields_set,
        category=request.category,
    )
    return LibrarySkillResponse.from_skill(
        await library.update_skill(library_skill_uuid, edit)
    )


@library_router.post("/{library_skill_uuid}/publish")
async def publish_library_skill(
    library_skill_uuid: str, _admin: PlatformAdmin, library: Library
) -> LibrarySkillResponse:
    """Publish (version + 1); a no-op for an already published skill."""
    return LibrarySkillResponse.from_skill(await library.publish(library_skill_uuid))


@library_router.post("/{library_skill_uuid}/deprecate")
async def deprecate_library_skill(
    library_skill_uuid: str, _admin: PlatformAdmin, library: Library
) -> LibrarySkillResponse:
    """Hide from the library; existing workspace copies are unaffected."""
    return LibrarySkillResponse.from_skill(await library.deprecate(library_skill_uuid))


@library_router.delete("/{library_skill_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_skill(
    library_skill_uuid: str, _admin: PlatformAdmin, library: Library
) -> None:
    """Delete permanently; workspace copies keep their content but lose the
    link to the library. Prefer deprecate."""
    await library.delete_skill(library_skill_uuid)

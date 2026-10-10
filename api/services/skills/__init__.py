"""Agent skills (Agent-Skills-style ``SKILL.md``): the platform library and
workspace skills. See ``service`` for the lifecycle rules, ``validation`` for
limits, ``frontmatter`` for the ``SKILL.md`` format and ``archive`` for zip
import/export.
"""

from loguru import logger

from api.db import db_client
from api.db.skill_client import SeedSyncReport
from api.services.skills.seeds import load_seeds
from api.services.skills.service import (
    ExportedSkill,
    LibraryDiff,
    LibraryEdit,
    LibraryService,
    SkillEdit,
    SkillService,
)


def get_skill_service() -> SkillService:
    """FastAPI dependency wiring the workspace service to the real DB."""
    return SkillService(skills=db_client, library=db_client, tools=db_client)


def get_library_service() -> LibraryService:
    """FastAPI dependency wiring the library service to the real DB."""
    return LibraryService(library=db_client)


async def sync_seed_library() -> SeedSyncReport:
    """Sync ``api/skills_library`` into the library (idempotent)."""
    report = await get_library_service().sync_seeds(load_seeds())
    logger.info(
        "Skill library seeds synced: created={} updated={} unchanged={} skipped={}",
        len(report.created),
        len(report.updated),
        len(report.unchanged),
        len(report.skipped),
    )
    if report.skipped:
        logger.warning(
            "Seed skills not synced, names held by API-authored library skills: {}",
            ", ".join(report.skipped),
        )
    return report


async def sync_seed_library_on_startup() -> None:
    """Startup hook: a failed sync is logged, never fatal, so a bad seed or a
    not-yet-migrated database cannot keep the API from starting."""
    try:
        await sync_seed_library()
    except Exception:  # noqa: BLE001 - startup must not fail on seeds
        logger.exception("Skill library seed sync failed")


__all__ = [
    "ExportedSkill",
    "LibraryDiff",
    "LibraryEdit",
    "LibraryService",
    "SkillEdit",
    "SkillService",
    "get_library_service",
    "get_skill_service",
    "sync_seed_library",
    "sync_seed_library_on_startup",
]

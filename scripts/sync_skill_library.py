"""Sync the seed skills in api/skills_library/<name>/SKILL.md into the
platform skill library.

The API also runs this at startup; use the script after editing a seed
without restarting, or to see what would change. Run from the repo root with
the api environment:

    python -m scripts.sync_skill_library

Idempotent: unchanged seeds are left alone; a changed seed replaces the
library content and, if published, bumps its version. Exits non-zero if a
seed is invalid.
"""

from __future__ import annotations

import asyncio
import sys

from api.errors.skills import SkillValidationError
from api.services.skills import sync_seed_library


async def _run() -> int:
    try:
        report = await sync_seed_library()
    except SkillValidationError as exc:
        print(f"Invalid seed skill: {exc.message}", file=sys.stderr)
        return 1
    print(
        f"created={list(report.created)} updated={list(report.updated)} "
        f"unchanged={list(report.unchanged)} skipped={list(report.skipped)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))

"""Move existing organizations onto platform-managed models.

Every organization with a stored v2 model configuration on the Dograh-managed
service (``dograh``) or on its own keys (``byok``) is switched to ``platform``,
keeping its voice, language and models wherever the platform offers an
equivalent. Workflow-level model overrides (drafts and published versions) are
converted the same way, and legacy provider overlays are dropped.

Before anything is written, every previous value is saved to a backup file, one
JSON object per organization, so ``--revert`` can restore it exactly. The
backup holds the organizations' old API keys: it is created owner-only and
should be deleted once the migration is confirmed.

Order matters. Deploy this release to every api pod first (older releases
can't read "platform" configurations), then turn PLATFORM_MODELS_ENABLED on
and run this script straight away: until an organization is migrated, its
customers can't save agents that still carry a provider override.

Run it in a maintenance window with PLATFORM_MODELS_ENABLED already on: plans
are computed up front and applied as computed, so model settings edited while
it runs are overwritten. Each organization's model configuration and its
workflows are written separately; if a run stops part way, re-running finishes
the rest (organizations already on platform are left alone), but only the first
run's backup can restore the original state. Organizations with no stored v2
configuration are not touched: bootstrap gives them the platform default.

Dry run (default) prints what would change::

    source venv/bin/activate && set -a && source api/.env && set +a \
        && python -m scripts.migrate_orgs_to_platform_models

Apply, writing the backup first::

    ... && python -m scripts.migrate_orgs_to_platform_models --apply \
        --backup platform-migration-backup.jsonl

Revert from a backup::

    ... && python -m scripts.migrate_orgs_to_platform_models \
        --revert platform-migration-backup.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2
from api.services.configuration.platform.migration import (
    migrate_to_platform,
    migrate_workflow_configurations,
)

MODEL_CONFIGURATION_KEY = OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value


@dataclass(slots=True)
class WorkflowChange:
    id: int
    before: dict[str, Any]
    after: dict[str, Any]
    notes: list[str]


@dataclass(slots=True)
class OrganizationPlan:
    organization_id: int
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    notes: list[str] = field(default_factory=list)
    workflows: list[WorkflowChange] = field(default_factory=list)
    definitions: list[WorkflowChange] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.after is not None or bool(self.workflows or self.definitions)


async def plan_organization(
    organization_id: int, stored: dict[str, Any] | None
) -> OrganizationPlan:
    plan = OrganizationPlan(organization_id=organization_id, before=stored, after=None)
    try:
        existing = (
            OrganizationAIModelConfigurationV2.model_validate(stored)
            if stored
            else None
        )
    except ValidationError:
        existing = None
        plan.notes.append("unparsable configuration replaced by the default")
    if existing is None or existing.mode != "platform":
        result = migrate_to_platform(existing)
        plan.after = OrganizationAIModelConfigurationV2(
            mode="platform", platform=result.configuration
        ).model_dump(mode="json", exclude_none=True)
        plan.notes.extend(result.notes)

    workflows = await db_client.list_workflows_for_model_configuration_migration(
        organization_id
    )
    for workflow in workflows:
        change = migrate_workflow_configurations(workflow.workflow_configurations)
        if change is not None:
            plan.workflows.append(
                WorkflowChange(workflow.id, workflow.workflow_configurations, *change)
            )
        for definition in workflow.definitions:
            change = migrate_workflow_configurations(definition.workflow_configurations)
            if change is not None:
                plan.definitions.append(
                    WorkflowChange(
                        definition.id, definition.workflow_configurations, *change
                    )
                )
    return plan


async def build_plans(organization_ids: set[int] | None) -> list[OrganizationPlan]:
    rows = await db_client.get_all_configurations_by_key(MODEL_CONFIGURATION_KEY)
    plans = []
    for row in sorted(rows, key=lambda r: r["organization_id"]):
        if organization_ids and row["organization_id"] not in organization_ids:
            continue
        plan = await plan_organization(row["organization_id"], row["value"])
        if plan.changed:
            plans.append(plan)
    return plans


async def apply_plan(plan: OrganizationPlan) -> None:
    if plan.after is not None:
        await db_client.upsert_configuration(
            plan.organization_id, MODEL_CONFIGURATION_KEY, plan.after
        )
    await db_client.bulk_update_workflow_model_configurations(
        organization_id=plan.organization_id,
        workflow_updates=[(change.id, change.after) for change in plan.workflows],
        definition_updates=[(change.id, change.after) for change in plan.definitions],
    )


def backup_record(plan: OrganizationPlan) -> dict[str, Any]:
    return {
        "organization_id": plan.organization_id,
        "model_configuration_v2": plan.before,
        "workflows": {str(change.id): change.before for change in plan.workflows},
        "definitions": {str(change.id): change.before for change in plan.definitions},
    }


async def revert(record: dict[str, Any]) -> None:
    organization_id = record["organization_id"]
    previous = record["model_configuration_v2"]
    if previous is None:
        await db_client.delete_configuration(organization_id, MODEL_CONFIGURATION_KEY)
    else:
        await db_client.upsert_configuration(
            organization_id, MODEL_CONFIGURATION_KEY, previous
        )
    await db_client.bulk_update_workflow_model_configurations(
        organization_id=organization_id,
        workflow_updates=[
            (int(workflow_id), value)
            for workflow_id, value in record["workflows"].items()
        ],
        definition_updates=[
            (int(definition_id), value)
            for definition_id, value in record["definitions"].items()
        ],
    )


def _print_plan(plan: OrganizationPlan) -> None:
    after = plan.after or {}
    platform = after.get("platform", {})
    summary = platform.get("pipeline_mode", "unchanged")
    print(
        f"org {plan.organization_id}: {(plan.before or {}).get('mode')} -> "
        f"platform/{summary}; {len(plan.workflows)} workflow(s), "
        f"{len(plan.definitions)} version(s)"
    )
    for note in plan.notes:
        print(f"    - {note}")
    for kind, changes in (("workflow", plan.workflows), ("version", plan.definitions)):
        for change in changes:
            print(f"    {kind} {change.id}: {'; '.join(change.notes) or 'updated'}")


def _open_backup(path: Path) -> TextIO:
    # Owner-only from creation: the backup holds the organizations' API keys.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--backup", type=Path, help="backup file to create (--apply)")
    parser.add_argument("--revert", type=Path, help="restore from a backup file")
    parser.add_argument(
        "--organization-id",
        type=int,
        action="append",
        help="limit to these organizations (repeatable)",
    )
    args = parser.parse_args()

    if args.revert:
        records = [
            json.loads(line)
            for line in args.revert.read_text().splitlines()
            if line.strip()
        ]
        only = set(args.organization_id or ())
        for record in records:
            if only and record["organization_id"] not in only:
                continue
            await revert(record)
            print(f"org {record['organization_id']}: restored")
        return 0

    plans = await build_plans(set(args.organization_id or ()) or None)
    for plan in plans:
        _print_plan(plan)
    print(f"{len(plans)} organization(s) to migrate")

    if not args.apply:
        print("Dry run: nothing written. Re-run with --apply --backup <file>.")
        return 0
    if args.backup is None:
        parser.error("--apply requires --backup")

    with _open_backup(args.backup) as backup:
        for plan in plans:
            backup.write(json.dumps(backup_record(plan)) + "\n")
    print(f"Backup written to {args.backup}")

    for plan in plans:
        await apply_plan(plan)
        print(f"org {plan.organization_id}: migrated")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

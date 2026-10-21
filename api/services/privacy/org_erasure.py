"""Daily erasure of organisations whose deletion grace period has ended.

For each organisation due, in this order, stopping at the first failure so the
next pass resumes where this one stopped:

1. every workflow run's stored objects (recordings, transcripts, per-track and
   observability audio), then the run rows, a batch at a time;
2. each prompt recording's audio, by the key on its row;
3. the organisation's own storage prefixes (campaign contact lists, knowledge
   base files, custom ambient noise);
4. under Stack Auth, the organisation's Stack team;
5. every remaining organisation-scoped row, in one transaction, leaving the
   organisation row as a tombstone.

Stored objects always go before the rows that name them, so an interrupted
pass never loses track of an object. Billing accounts, the credit ledger and
usage cycles are kept as accounting records. Members keep their user accounts
(they may belong to other organisations) and can delete them themselves.
``ORG_ERASURE_ENABLED=false`` turns the cron into a no-op.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from loguru import logger

from api import constants
from api.db import db_client
from api.db.org_erasure_client import PromptRecordingObject
from api.services.auth.stack_auth import StackAuthDeletionError, stackauth

# TODO(PR B): these helpers become public in api.services.retention.purge.
from api.services.retention.purge import (
    StorageResolver,
    _current_backend,
    _default_storage_resolver,
    _delete_run_objects,
)

ORGANIZATION_PAGE_SIZE = 100
RUN_BATCH_SIZE = 100


def organization_storage_prefixes(organization_id: int) -> tuple[str, ...]:
    """Prefixes that hold only this organisation's objects.

    ``recordings/`` is not one of them: it also holds every run's audio
    (``recordings/{run_id}/...``), and run ids and organisation ids are both
    integers. Prompt recordings are deleted one by one from their rows instead.
    """
    return (
        f"campaigns/{organization_id}/",
        f"knowledge_base/{organization_id}/",
        f"ambient-noise/{organization_id}/",
    )


def is_prompt_recording_key(
    organization_id: int, recording: PromptRecordingObject
) -> bool:
    """Whether the row's key is where this organisation's upload put it:
    ``recordings/{organization_id}/{recording_id}/{filename}``.

    The key on the row comes from the client, so anything else (another
    organisation's object, a run's audio) is never deleted on its say-so.
    """
    if not recording.recording_id or "/" in recording.recording_id:
        return False
    return bool(
        re.fullmatch(
            rf"recordings/{organization_id}/{re.escape(recording.recording_id)}/[^/]+",
            recording.storage_key or "",
        )
    )


@dataclass
class OrgErasureResult:
    organizations_erased: int = 0
    organizations_deferred: int = 0
    runs_deleted: int = 0
    objects_deleted: int = 0


class ErasureDeferred(Exception):
    """A stored object could not be deleted; retry the organisation later."""


async def _erase_runs(
    organization_id: int, resolve_storage: StorageResolver, result: OrgErasureResult
) -> None:
    while True:
        runs = await db_client.get_organization_workflow_runs_for_erasure(
            organization_id, limit=RUN_BATCH_SIZE
        )
        if not runs:
            return
        cleared: list[int] = []
        for run in runs:
            deleted = await _delete_run_objects(run, resolve_storage)
            if deleted is None:
                # Delete the rows whose objects are gone, then stop: the rest
                # are retried on the next pass.
                result.runs_deleted += (
                    await db_client.delete_organization_workflow_runs(
                        organization_id, cleared
                    )
                )
                raise ErasureDeferred(f"objects of workflow run {run.id}")
            result.objects_deleted += deleted
            cleared.append(run.id)
        result.runs_deleted += await db_client.delete_organization_workflow_runs(
            organization_id, cleared
        )


async def _erase_prompt_recordings(
    organization_id: int, resolve_storage: StorageResolver, result: OrgErasureResult
) -> None:
    for recording in await db_client.get_organization_prompt_recordings(
        organization_id
    ):
        if not is_prompt_recording_key(organization_id, recording):
            logger.warning(
                f"Organisation erasure skipped the object of prompt recording "
                f"{recording.id} (organisation {organization_id}): its key is "
                "not one this organisation uploaded"
            )
            continue
        try:
            deleted = await resolve_storage(recording.storage_backend).adelete_file(
                recording.storage_key
            )
        except Exception:
            deleted = False
        if not deleted:
            raise ErasureDeferred(f"audio of prompt recording {recording.id}")
        result.objects_deleted += 1


async def _erase_prefixes(
    organization_id: int, resolve_storage: StorageResolver, result: OrgErasureResult
) -> None:
    storage = resolve_storage(_current_backend())
    for prefix in organization_storage_prefixes(organization_id):
        try:
            result.objects_deleted += await storage.adelete_prefix(prefix)
        except Exception as exc:
            raise ErasureDeferred(f"objects under {prefix}") from exc


async def _delete_identity_provider_team(organization_id: int) -> None:
    if constants.AUTH_PROVIDER != "stack":
        return
    organization = await db_client.get_organization_by_id(organization_id)
    if organization is None or organization.erased_at is not None:
        return
    try:
        await stackauth.delete_team(organization.provider_id)
    except StackAuthDeletionError as exc:
        raise ErasureDeferred("the Stack Auth team") from exc


async def erase_organization(
    organization_id: int,
    *,
    now: datetime,
    resolve_storage: StorageResolver,
    result: Optional[OrgErasureResult] = None,
) -> bool:
    """Erase one organisation whose deletion is due. True once it is erased."""
    result = result or OrgErasureResult()
    state = await db_client.get_organization_deletion_state(organization_id)
    if state is None or not state.is_pending:
        return bool(state and state.is_erased)
    if state.scheduled_for is None or state.scheduled_for > now:
        return False

    await _erase_runs(organization_id, resolve_storage, result)
    await _erase_prompt_recordings(organization_id, resolve_storage, result)
    await _erase_prefixes(organization_id, resolve_storage, result)
    await _delete_identity_provider_team(organization_id)
    erased = await db_client.erase_organization_rows(organization_id, erased_at=now)
    if not erased:
        # A run was created after the run phase; the next pass handles it.
        raise ErasureDeferred("rows created during erasure")
    return True


async def erase_deleted_organizations(
    *,
    now: Optional[datetime] = None,
    resolve_storage: Optional[StorageResolver] = None,
) -> OrgErasureResult:
    """Erase every organisation whose deletion grace period has ended.

    Idempotent and resumable: each phase commits as it goes, and a failure
    only defers that organisation to the next pass.
    """
    now = now or datetime.now(UTC)
    resolve_storage = resolve_storage or _default_storage_resolver()
    result = OrgErasureResult()

    after_id = 0
    while True:
        organization_ids = await db_client.get_organizations_due_for_erasure(
            now=now, after_id=after_id, limit=ORGANIZATION_PAGE_SIZE
        )
        if not organization_ids:
            break
        after_id = organization_ids[-1]
        for organization_id in organization_ids:
            try:
                if await erase_organization(
                    organization_id,
                    now=now,
                    resolve_storage=resolve_storage,
                    result=result,
                ):
                    result.organizations_erased += 1
                    logger.info(f"Organisation {organization_id} erased")
            except ErasureDeferred as exc:
                result.organizations_deferred += 1
                logger.error(
                    f"Organisation erasure deferred for {organization_id}: could "
                    f"not delete {exc}"
                )
            except Exception as exc:
                # One organisation's failure must not hold up the others.
                result.organizations_deferred += 1
                logger.error(
                    f"Organisation erasure failed for {organization_id}: "
                    f"{type(exc).__name__}"
                )
        if len(organization_ids) < ORGANIZATION_PAGE_SIZE:
            break

    logger.info(
        "Organisation erasure: {} erased, {} deferred, {} runs and {} objects deleted",
        result.organizations_erased,
        result.organizations_deferred,
        result.runs_deleted,
        result.objects_deleted,
    )
    return result

"""Daily data-retention purge (GDPR Art. 5(1)(e), storage limitation).

What the privacy policy promises, and what this enforces:

* Call recordings, transcripts and call content are deleted once a run is
  older than its organization's ``call_data_retention_days`` (default 90,
  1-365). Stored objects go first; only when every object of a run is gone is
  its row scrubbed and marked, so a storage outage just defers the run to the
  next pass. Campaign contact lists (the CSV object and each queued run's
  row) follow the same period.
* Widget visitor technical data (embed session IP and user agent) is cleared
  after ``VISITOR_DATA_RETENTION``.
* Outgoing webhook payloads and errors are cleared after
  ``WEBHOOK_PAYLOAD_RETENTION``.

Rows are scrubbed, not deleted, so billing and usage history stays intact.
Logs carry counts and ids only, never the content being deleted.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Optional

from loguru import logger

from api.db import db_client
from api.db.retention_client import ExpiredCampaign, ExpiredWorkflowRun
from api.services.filesystem import BaseFileSystem
from api.services.organization_preferences import get_organization_preferences

VISITOR_DATA_RETENTION = timedelta(days=30)
WEBHOOK_PAYLOAD_RETENTION = timedelta(days=30)

ORGANIZATION_PAGE_SIZE = 100
RUN_BATCH_SIZE = 100
CAMPAIGN_BATCH_SIZE = 50
ROW_BATCH_SIZE = 1000

StorageResolver = Callable[[str], BaseFileSystem]


@dataclass
class RetentionPurgeResult:
    organizations: int = 0
    runs_purged: int = 0
    runs_deferred: int = 0
    objects_deleted: int = 0
    campaigns_purged: int = 0
    campaigns_deferred: int = 0
    queued_runs_cleared: int = 0
    embed_sessions_cleared: int = 0
    webhook_deliveries_cleared: int = 0


def _default_storage_resolver() -> StorageResolver:
    """Storage per backend code, reusing the process-wide instance when it fits."""
    from api.services.storage import (
        get_current_storage_backend,
        get_storage_for_backend,
        storage_fs,
    )

    cache: dict[str, BaseFileSystem] = {get_current_storage_backend().value: storage_fs}

    def resolve(backend: str) -> BaseFileSystem:
        if backend not in cache:
            cache[backend] = get_storage_for_backend(backend)
        return cache[backend]

    return resolve


def _current_backend() -> str:
    from api.services.storage import get_current_storage_backend

    return get_current_storage_backend().value


def _is_run_artifact_key(run_id: int, key: str) -> bool:
    """Whether ``key`` is one of this run's own objects.

    ``recordings/`` is shared with agent prompt audio
    (``recordings/{org_id}/{recording_id}/{file}``), so a key read from the
    run row is only deleted when it is unmistakably this run's.
    """
    return bool(
        re.fullmatch(
            rf"(?:recordings/{run_id}(?:\.wav|/(?:user|bot)\.wav|/noveum/.+)"
            rf"|transcripts/{run_id}\.txt)",
            key,
        )
    )


def _run_object_keys(run: ExpiredWorkflowRun) -> dict[str, str]:
    """Every object key the run references, mapped to its storage backend."""
    keys: dict[str, str] = {}
    for key in (run.recording_url, run.transcript_url):
        if key:
            keys[key] = run.storage_backend
    # The per-track uploads are not always recorded in ``extra`` (a failed
    # metadata write), so delete their deterministic keys regardless.
    for key in (
        f"recordings/{run.id}.wav",
        f"recordings/{run.id}/user.wav",
        f"recordings/{run.id}/bot.wav",
        f"transcripts/{run.id}.txt",
    ):
        keys.setdefault(key, run.storage_backend)
    recordings = run.extra.get("recordings")
    if isinstance(recordings, dict):
        for artifact in recordings.values():
            if isinstance(artifact, str):
                keys.setdefault(artifact, run.storage_backend)
            elif isinstance(artifact, dict) and isinstance(
                artifact.get("storage_key"), str
            ):
                keys[artifact["storage_key"]] = (
                    artifact.get("storage_backend") or run.storage_backend
                )
    return {
        key: backend
        for key, backend in keys.items()
        if _is_run_artifact_key(run.id, key)
    }


async def _delete_run_objects(
    run: ExpiredWorkflowRun, resolve_storage: StorageResolver
) -> Optional[int]:
    """Delete every stored object of ``run``; None if any deletion failed."""
    deleted = 0
    try:
        for key, backend in _run_object_keys(run).items():
            if not await resolve_storage(backend).adelete_file(key):
                return None
            deleted += 1
        # Noveum observability audio segments (one object per utterance).
        deleted += await resolve_storage(run.storage_backend).adelete_prefix(
            f"recordings/{run.id}/noveum/"
        )
    except Exception as exc:
        logger.warning(
            f"Retention purge could not delete objects of workflow run {run.id}: "
            f"{type(exc).__name__}"
        )
        return None
    return deleted


async def _purge_organization_runs(
    organization_id: int,
    cutoff: datetime,
    now: datetime,
    resolve_storage: StorageResolver,
    result: RetentionPurgeResult,
) -> None:
    after_id = 0
    while True:
        runs = await db_client.get_workflow_runs_past_retention(
            organization_id=organization_id,
            created_before=cutoff,
            after_id=after_id,
            limit=RUN_BATCH_SIZE,
        )
        if not runs:
            return
        after_id = runs[-1].id

        cleared: list[int] = []
        for run in runs:
            deleted = await _delete_run_objects(run, resolve_storage)
            if deleted is None:
                result.runs_deferred += 1
                continue
            result.objects_deleted += deleted
            cleared.append(run.id)

        result.runs_purged += await db_client.scrub_workflow_runs_call_content(
            organization_id=organization_id, run_ids=cleared, purged_at=now
        )
        if len(runs) < RUN_BATCH_SIZE:
            return


def _campaign_csv_key(organization_id: int, campaign: ExpiredCampaign) -> Optional[str]:
    """The uploaded CSV of a campaign, if it is one this organization owns."""
    if campaign.source_type != "csv" or not campaign.source_id:
        return None
    if not campaign.source_id.startswith(f"campaigns/{organization_id}/"):
        return None
    return campaign.source_id


async def _purge_organization_campaigns(
    organization_id: int,
    cutoff: datetime,
    now: datetime,
    resolve_storage: StorageResolver,
    result: RetentionPurgeResult,
) -> None:
    after_id = 0
    while True:
        campaigns = await db_client.get_campaigns_past_retention(
            organization_id=organization_id,
            inactive_before=cutoff,
            after_id=after_id,
            limit=CAMPAIGN_BATCH_SIZE,
        )
        if not campaigns:
            break
        after_id = campaigns[-1].id

        for campaign in campaigns:
            csv_key = _campaign_csv_key(organization_id, campaign)
            if csv_key and await db_client.is_campaign_source_shared(
                organization_id=organization_id,
                source_id=csv_key,
                campaign_id=campaign.id,
            ):
                csv_key = None
            if csv_key:
                try:
                    deleted = await resolve_storage(_current_backend()).adelete_file(
                        csv_key
                    )
                except Exception:
                    deleted = False
                if not deleted:
                    result.campaigns_deferred += 1
                    continue
                result.objects_deleted += 1
            if await db_client.scrub_campaign_contact_data(
                organization_id=organization_id,
                campaign_id=campaign.id,
                purged_at=now,
            ):
                result.campaigns_purged += 1
        if len(campaigns) < CAMPAIGN_BATCH_SIZE:
            break

    # Rows dialled long ago in a campaign that is still running.
    while True:
        cleared = await db_client.scrub_finished_queued_runs_context(
            organization_id=organization_id,
            created_before=cutoff,
            limit=ROW_BATCH_SIZE,
        )
        result.queued_runs_cleared += cleared
        if cleared < ROW_BATCH_SIZE:
            break


async def _scrub_in_batches(scrub, created_before: datetime) -> int:
    total = 0
    while True:
        cleared = await scrub(created_before=created_before, limit=ROW_BATCH_SIZE)
        total += cleared
        if cleared < ROW_BATCH_SIZE:
            return total


async def purge_expired_data(
    *,
    now: Optional[datetime] = None,
    resolve_storage: Optional[StorageResolver] = None,
) -> RetentionPurgeResult:
    """Run one retention pass over every organization. Safe to re-run."""
    now = now or datetime.now(UTC)
    resolve_storage = resolve_storage or _default_storage_resolver()
    result = RetentionPurgeResult()

    after_id = 0
    while True:
        organization_ids = await db_client.get_organization_ids_page(
            after_id=after_id, limit=ORGANIZATION_PAGE_SIZE
        )
        if not organization_ids:
            break
        after_id = organization_ids[-1]
        for organization_id in organization_ids:
            result.organizations += 1
            try:
                preferences = await get_organization_preferences(organization_id)
                cutoff = now - timedelta(days=preferences.call_data_retention_days)
                await _purge_organization_runs(
                    organization_id, cutoff, now, resolve_storage, result
                )
                await _purge_organization_campaigns(
                    organization_id, cutoff, now, resolve_storage, result
                )
            except Exception as exc:
                # One organization's failure must not keep the others' data.
                logger.error(
                    f"Retention purge failed for organization {organization_id}: "
                    f"{type(exc).__name__}"
                )
        if len(organization_ids) < ORGANIZATION_PAGE_SIZE:
            break

    result.embed_sessions_cleared = await _scrub_in_batches(
        db_client.scrub_embed_session_visitor_data, now - VISITOR_DATA_RETENTION
    )
    result.webhook_deliveries_cleared = await _scrub_in_batches(
        db_client.scrub_finished_webhook_delivery_payloads,
        now - WEBHOOK_PAYLOAD_RETENTION,
    )

    logger.info(
        "Retention purge: {} organizations, {} runs purged ({} deferred), "
        "{} objects deleted, {} campaigns purged ({} deferred), "
        "{} queued runs, {} embed sessions, {} webhook deliveries cleared",
        result.organizations,
        result.runs_purged,
        result.runs_deferred,
        result.objects_deleted,
        result.campaigns_purged,
        result.campaigns_deferred,
        result.queued_runs_cleared,
        result.embed_sessions_cleared,
        result.webhook_deliveries_cleared,
    )
    return result

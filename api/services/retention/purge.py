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
* Knowledge base documents and prompt recordings that were deleted while
  deletes were still soft (archived rows) lose their stored file, then their
  row, like a delete does now.

Rows are scrubbed, not deleted, so billing and usage history stays intact.
Logs carry counts and ids only, never the content being deleted. A dry run
(``RETENTION_PURGE_DRY_RUN``) logs per-organization counts of what would be
purged and changes nothing.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Optional

from loguru import logger

from api.db import db_client
from api.db.retention_client import (
    CampaignScrubOutcome,
    ExpiredCampaign,
    ExpiredWorkflowRun,
)
from api.services.filesystem import BaseFileSystem
from api.services.organization_preferences import get_call_data_retention_days

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
    organizations_skipped: int = 0
    runs_purged: int = 0
    runs_deferred: int = 0
    objects_deleted: int = 0
    campaigns_purged: int = 0
    campaigns_deferred: int = 0
    queued_runs_cleared: int = 0
    embed_sessions_cleared: int = 0
    webhook_deliveries_cleared: int = 0
    archived_documents_deleted: int = 0
    archived_recordings_deleted: int = 0
    archived_files_deferred: int = 0


def default_storage_resolver() -> StorageResolver:
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


def current_storage_backend() -> str:
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


def run_object_keys(run: ExpiredWorkflowRun) -> dict[str, str]:
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


async def delete_run_objects(
    run: ExpiredWorkflowRun, resolve_storage: StorageResolver
) -> Optional[int]:
    """Delete every stored object of ``run``; None if any deletion failed."""
    deleted = 0
    try:
        for key, backend in run_object_keys(run).items():
            if not await resolve_storage(backend).adelete_file(key):
                return None
            deleted += 1
        # Noveum observability audio segments (one object per utterance).
        deleted += await resolve_storage(run.storage_backend).adelete_prefix(
            f"recordings/{run.id}/noveum/"
        )
    except Exception as exc:
        logger.warning(
            f"Could not delete the stored objects of workflow run {run.id}: "
            f"{type(exc).__name__}"
        )
        return None
    return deleted


async def _count_organization_runs(organization_id: int, cutoff: datetime) -> int:
    count = 0
    after_id = 0
    while True:
        runs = await db_client.get_workflow_runs_past_retention(
            organization_id=organization_id,
            created_before=cutoff,
            after_id=after_id,
            limit=RUN_BATCH_SIZE,
        )
        count += len(runs)
        if len(runs) < RUN_BATCH_SIZE:
            return count
        after_id = runs[-1].id


async def _count_organization_campaigns(organization_id: int, cutoff: datetime) -> int:
    count = 0
    after_id = 0
    while True:
        campaigns = await db_client.get_campaigns_past_retention(
            organization_id=organization_id,
            inactive_before=cutoff,
            after_id=after_id,
            limit=CAMPAIGN_BATCH_SIZE,
        )
        count += len(campaigns)
        if len(campaigns) < CAMPAIGN_BATCH_SIZE:
            return count
        after_id = campaigns[-1].id


async def _log_organization_dry_run(
    organization_id: int, cutoff: datetime, now: datetime
) -> None:
    """One line per organization: what a real pass would purge, counts only."""
    runs = await _count_organization_runs(organization_id, cutoff)
    campaigns = await _count_organization_campaigns(organization_id, cutoff)
    queued_rows = await db_client.count_finished_queued_runs_context(
        organization_id=organization_id, inactive_before=cutoff
    )
    widget_sessions = await db_client.count_embed_session_visitor_data(
        organization_id=organization_id, created_before=now - VISITOR_DATA_RETENTION
    )
    webhook_deliveries = await db_client.count_finished_webhook_delivery_payloads(
        organization_id=organization_id,
        created_before=now - WEBHOOK_PAYLOAD_RETENTION,
    )
    documents, recordings = await _archived_uploads(organization_id)
    logger.info(
        "Retention purge dry run: organization={} runs={} campaigns={} "
        "queued_rows={} widget_sessions={} webhook_deliveries={} "
        "archived_documents={} archived_recordings={}",
        organization_id,
        runs,
        campaigns,
        queued_rows,
        widget_sessions,
        webhook_deliveries,
        len(documents),
        len(recordings),
    )


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
            deleted = await delete_run_objects(run, resolve_storage)
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


def campaign_csv_key(organization_id: int, campaign: ExpiredCampaign) -> Optional[str]:
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
            csv_key = campaign_csv_key(organization_id, campaign)
            if csv_key and await db_client.is_campaign_source_shared(
                organization_id=organization_id,
                source_id=csv_key,
                campaign_id=campaign.id,
            ):
                csv_key = None

            async def delete_csv(key: Optional[str] = csv_key) -> bool:
                # Called by the scrub once the campaign is confirmed eligible
                # under its row lock, so an active campaign keeps its list.
                if key is None:
                    return True
                try:
                    storage = resolve_storage(current_storage_backend())
                    deleted = await storage.adelete_file(key)
                except Exception:
                    deleted = False
                if deleted:
                    result.objects_deleted += 1
                return deleted

            outcome = await db_client.scrub_campaign_contact_data(
                organization_id=organization_id,
                campaign_id=campaign.id,
                purged_at=now,
                delete_source=delete_csv,
            )
            if outcome is CampaignScrubOutcome.PURGED:
                result.campaigns_purged += 1
            elif outcome is CampaignScrubOutcome.DEFERRED:
                result.campaigns_deferred += 1
        if len(campaigns) < CAMPAIGN_BATCH_SIZE:
            break

    # Contact rows of long-finished campaigns whose purge above was deferred.
    while True:
        cleared = await db_client.scrub_finished_queued_runs_context(
            organization_id=organization_id,
            inactive_before=cutoff,
            limit=ROW_BATCH_SIZE,
        )
        result.queued_runs_cleared += cleared
        if cleared < ROW_BATCH_SIZE:
            break


async def _archived_uploads(organization_id: int):
    """Every archived document and recording of the organization."""
    documents, recordings = [], []
    for fetch, out in (
        (db_client.get_archived_knowledge_base_documents, documents),
        (db_client.get_archived_workflow_recordings, recordings),
    ):
        after_id = 0
        while True:
            page = await fetch(
                organization_id=organization_id,
                after_id=after_id,
                limit=ROW_BATCH_SIZE,
            )
            out.extend(public_id for _id, public_id in page)
            if len(page) < ROW_BATCH_SIZE:
                break
            after_id = page[-1][0]
    return documents, recordings


async def _purge_organization_archived_uploads(
    organization_id: int,
    resolve_storage: StorageResolver,
    result: RetentionPurgeResult,
) -> None:
    """Hard-delete uploads that were only archived: stored file first, then row."""
    from api.services.privacy.stored_files import (
        StoredFileDeleteError,
        delete_knowledge_base_document,
        delete_workflow_recording,
    )

    documents, recordings = await _archived_uploads(organization_id)
    for document_uuid in documents:
        try:
            if await delete_knowledge_base_document(
                organization_id=organization_id,
                document_uuid=document_uuid,
                resolve_storage=resolve_storage,
            ):
                result.archived_documents_deleted += 1
        except StoredFileDeleteError:
            result.archived_files_deferred += 1
    for recording_id in recordings:
        try:
            if await delete_workflow_recording(
                organization_id=organization_id,
                recording_id=recording_id,
                resolve_storage=resolve_storage,
            ):
                result.archived_recordings_deleted += 1
        except StoredFileDeleteError:
            result.archived_files_deferred += 1


async def _scrub_in_batches(scrub, created_before: datetime) -> int:
    total = 0
    while True:
        cleared = await scrub(created_before=created_before, limit=ROW_BATCH_SIZE)
        total += cleared
        if cleared < ROW_BATCH_SIZE:
            return total


async def _purge_organization(
    organization_id: int,
    now: datetime,
    resolve_storage: Optional[StorageResolver],
    dry_run: bool,
    result: RetentionPurgeResult,
) -> None:
    retention_days = await get_call_data_retention_days(organization_id)
    if retention_days is None:
        # Deleting at the default could destroy data the organization chose
        # to keep longer, so an unreadable setting keeps everything.
        result.organizations_skipped += 1
        logger.error(
            f"Retention purge skipped organization {organization_id}: its stored "
            "call_data_retention_days is invalid"
        )
        return
    cutoff = now - timedelta(days=retention_days)
    if dry_run:
        await _log_organization_dry_run(organization_id, cutoff, now)
        return

    deferred_before = result.runs_deferred
    await _purge_organization_runs(
        organization_id, cutoff, now, resolve_storage, result
    )
    runs_deferred = result.runs_deferred - deferred_before
    if runs_deferred:
        logger.error(
            f"Retention purge deferred {runs_deferred} runs of organization "
            f"{organization_id}: their stored objects could not be deleted"
        )
    await _purge_organization_campaigns(
        organization_id, cutoff, now, resolve_storage, result
    )
    await _purge_organization_archived_uploads(organization_id, resolve_storage, result)


async def purge_expired_data(
    *,
    now: Optional[datetime] = None,
    resolve_storage: Optional[StorageResolver] = None,
    dry_run: bool = False,
) -> RetentionPurgeResult:
    """Run one retention pass over every organization. Safe to re-run.

    With ``dry_run`` nothing is deleted or scrubbed; each organization's counts
    of what would be purged are logged instead.
    """
    now = now or datetime.now(UTC)
    if not dry_run:
        resolve_storage = resolve_storage or default_storage_resolver()
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
                await _purge_organization(
                    organization_id, now, resolve_storage, dry_run, result
                )
            except Exception as exc:
                # One organization's failure must not keep the others' data.
                logger.error(
                    f"Retention purge failed for organization {organization_id}: "
                    f"{type(exc).__name__}"
                )
        if len(organization_ids) < ORGANIZATION_PAGE_SIZE:
            break

    if dry_run:
        logger.info(
            "Retention purge dry run finished: {} organizations checked "
            "({} skipped), nothing deleted",
            result.organizations,
            result.organizations_skipped,
        )
        return result

    result.embed_sessions_cleared = await _scrub_in_batches(
        db_client.scrub_embed_session_visitor_data, now - VISITOR_DATA_RETENTION
    )
    result.webhook_deliveries_cleared = await _scrub_in_batches(
        db_client.scrub_finished_webhook_delivery_payloads,
        now - WEBHOOK_PAYLOAD_RETENTION,
    )

    logger.info(
        "Retention purge: {} organizations ({} skipped), "
        "{} runs purged ({} deferred), "
        "{} objects deleted, {} campaigns purged ({} deferred), "
        "{} queued runs, {} embed sessions, {} webhook deliveries cleared, "
        "{} archived documents and {} archived recordings deleted ({} deferred)",
        result.organizations,
        result.organizations_skipped,
        result.runs_purged,
        result.runs_deferred,
        result.objects_deleted,
        result.campaigns_purged,
        result.campaigns_deferred,
        result.queued_runs_cleared,
        result.embed_sessions_cleared,
        result.webhook_deliveries_cleared,
        result.archived_documents_deleted,
        result.archived_recordings_deleted,
        result.archived_files_deferred,
    )
    return result

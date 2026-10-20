"""Database access for the data-retention purge (GDPR storage limitation).

The purge service (``api/services/retention``) decides *what* is past its
retention period; this client finds those rows in bounded, keyset-paged batches
and scrubs their personal content in place. Rows are scrubbed rather than
deleted so billing and usage history (status, timestamps, duration, cost) keeps
adding up after the call content is gone.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Text, cast, func, or_, select, update

from api.db.base_client import BaseDBClient
from api.db.models import (
    CampaignModel,
    EmbedSessionModel,
    OrganizationModel,
    QueuedRunModel,
    WebhookDeliveryModel,
    WorkflowModel,
    WorkflowRunModel,
    WorkflowRunTextSessionModel,
)

# Marker stamped into ``workflow_runs.extra`` once a run's call content is gone,
# so later passes skip it.
WORKFLOW_RUN_PURGED_AT_KEY = "purged_at"
# Marker stamped into ``campaigns.orchestrator_metadata`` once a campaign's
# contact list (CSV object and queued-run context) is gone.
CAMPAIGN_PURGED_AT_KEY = "retention_purged_at"

# What survives a purge. Everything else in these JSON columns is dropped.
# ``extra``: run-configuration flags, no personal data (recording metadata is
# dropped with the recordings themselves).
WORKFLOW_RUN_EXTRA_KEPT_KEYS = frozenset({"use_draft", "campaign_traffic_split"})
# ``gathered_context``: the call outcome labels that usage reports aggregate.
WORKFLOW_RUN_GATHERED_CONTEXT_KEPT_KEYS = frozenset(
    {"call_status", "call_disposition", "mapped_call_disposition"}
)

TERMINAL_CAMPAIGN_STATES = ("completed", "failed")
# A campaign idle in one of these states past the retention period cannot be
# resumed once its contact list is deleted, so the purge fails it first.
IDLE_CAMPAIGN_STATES = ("created", "paused")
TERMINAL_QUEUED_RUN_STATES = ("processed", "failed")
TERMINAL_WEBHOOK_DELIVERY_STATES = ("succeeded", "dead_letter")


@dataclass(frozen=True)
class ExpiredWorkflowRun:
    """What the purge needs to know about a run to delete its stored objects."""

    id: int
    recording_url: Optional[str]
    transcript_url: Optional[str]
    storage_backend: str
    extra: dict[str, Any]


@dataclass(frozen=True)
class ExpiredCampaign:
    id: int
    state: str
    source_type: str
    source_id: str


def _workflow_run_not_purged():
    return WorkflowRunModel.extra[WORKFLOW_RUN_PURGED_AT_KEY].as_string().is_(None)


def _campaign_not_purged():
    return (
        CampaignModel.orchestrator_metadata[CAMPAIGN_PURGED_AT_KEY]
        .as_string()
        .is_(None)
    )


def _campaign_last_activity():
    """The latest moment anything happened on a campaign."""
    return func.greatest(
        CampaignModel.created_at,
        func.coalesce(CampaignModel.last_activity_at, CampaignModel.created_at),
        func.coalesce(CampaignModel.completed_at, CampaignModel.created_at),
    )


class RetentionClient(BaseDBClient):
    """Finds and scrubs rows that are past their retention period."""

    async def get_organization_ids_page(
        self, *, after_id: int = 0, limit: int = 100
    ) -> list[int]:
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel.id)
                .where(OrganizationModel.id > after_id)
                .order_by(OrganizationModel.id)
                .limit(limit)
            )
            return list(result.scalars().all())

    # --- workflow runs -----------------------------------------------------

    async def get_workflow_runs_past_retention(
        self,
        *,
        organization_id: int,
        created_before: datetime,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[ExpiredWorkflowRun]:
        """Unpurged runs of one organization created before ``created_before``.

        Keyset-paged by id: a run whose objects could not be deleted stays
        unpurged, so paging by ``after_id`` is what keeps one pass from
        returning it again and again.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    WorkflowRunModel.id,
                    WorkflowRunModel.recording_url,
                    WorkflowRunModel.transcript_url,
                    WorkflowRunModel.storage_backend,
                    WorkflowRunModel.extra,
                )
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.created_at < created_before,
                    WorkflowRunModel.id > after_id,
                    _workflow_run_not_purged(),
                )
                .order_by(WorkflowRunModel.id)
                .limit(limit)
            )
            return [
                ExpiredWorkflowRun(
                    id=row.id,
                    recording_url=row.recording_url,
                    transcript_url=row.transcript_url,
                    storage_backend=row.storage_backend,
                    extra=row.extra if isinstance(row.extra, dict) else {},
                )
                for row in result.all()
            ]

    async def scrub_workflow_runs_call_content(
        self,
        *,
        organization_id: int,
        run_ids: list[int],
        purged_at: datetime,
    ) -> int:
        """Clear the call content of these runs and stamp the purge marker.

        Clears recording/transcript keys, live transcript logs, call context
        (caller and called numbers, extracted variables), annotations, the
        public share token and the text-chat transcript. Keeps status,
        timestamps, usage and cost, plus the keys in
        ``WORKFLOW_RUN_EXTRA_KEPT_KEYS`` / ``WORKFLOW_RUN_GATHERED_CONTEXT_KEPT_KEYS``.
        Only runs that belong to ``organization_id`` are touched.

        Returns the number of runs scrubbed.
        """
        if not run_ids:
            return 0
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.id.in_(run_ids),
                    _workflow_run_not_purged(),
                )
                .with_for_update(of=WorkflowRunModel)
            )
            runs = list(result.scalars().all())
            for run in runs:
                extra = run.extra if isinstance(run.extra, dict) else {}
                gathered = (
                    run.gathered_context
                    if isinstance(run.gathered_context, dict)
                    else {}
                )
                run.recording_url = None
                run.transcript_url = None
                run.logs = {}
                run.initial_context = {}
                run.annotations = {}
                run.public_access_token = None
                run.gathered_context = {
                    key: value
                    for key, value in gathered.items()
                    if key in WORKFLOW_RUN_GATHERED_CONTEXT_KEPT_KEYS
                }
                run.extra = {
                    **{
                        key: value
                        for key, value in extra.items()
                        if key in WORKFLOW_RUN_EXTRA_KEPT_KEYS
                    },
                    WORKFLOW_RUN_PURGED_AT_KEY: purged_at.isoformat(),
                }

            scrubbed_ids = [run.id for run in runs]
            if scrubbed_ids:
                await session.execute(
                    update(WorkflowRunTextSessionModel)
                    .where(
                        WorkflowRunTextSessionModel.workflow_run_id.in_(scrubbed_ids)
                    )
                    .values(session_data={}, checkpoint={})
                )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return len(scrubbed_ids)

    # --- campaigns ---------------------------------------------------------

    async def get_campaigns_past_retention(
        self,
        *,
        organization_id: int,
        inactive_before: datetime,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[ExpiredCampaign]:
        """Unpurged campaigns with no activity since ``inactive_before``.

        Only finished (completed/failed) campaigns, and ones left idle in
        created/paused; a syncing or running campaign is still using its list.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    CampaignModel.id,
                    CampaignModel.state,
                    CampaignModel.source_type,
                    CampaignModel.source_id,
                )
                .where(
                    CampaignModel.organization_id == organization_id,
                    CampaignModel.state.in_(
                        TERMINAL_CAMPAIGN_STATES + IDLE_CAMPAIGN_STATES
                    ),
                    _campaign_last_activity() < inactive_before,
                    CampaignModel.id > after_id,
                    _campaign_not_purged(),
                )
                .order_by(CampaignModel.id)
                .limit(limit)
            )
            return [
                ExpiredCampaign(
                    id=row.id,
                    state=row.state,
                    source_type=row.source_type,
                    source_id=row.source_id,
                )
                for row in result.all()
            ]

    async def is_campaign_source_shared(
        self, *, organization_id: int, source_id: str, campaign_id: int
    ) -> bool:
        """Whether another unpurged campaign still uses this source.

        Redial campaigns inherit their parent's ``source_id``, so the CSV may
        only go once the last campaign that references it is purged.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(CampaignModel.id)
                .where(
                    CampaignModel.organization_id == organization_id,
                    CampaignModel.source_id == source_id,
                    CampaignModel.id != campaign_id,
                    _campaign_not_purged(),
                )
                .limit(1)
            )
            return result.first() is not None

    async def scrub_campaign_contact_data(
        self,
        *,
        organization_id: int,
        campaign_id: int,
        purged_at: datetime,
    ) -> bool:
        """Clear every queued run's contact row and mark the campaign purged.

        A campaign still idle in created/paused is failed first: without its
        contact list it can never run. Returns False when the campaign is not
        in this organization, was purged already, or became active meanwhile.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(CampaignModel)
                .where(
                    CampaignModel.id == campaign_id,
                    CampaignModel.organization_id == organization_id,
                    CampaignModel.state.in_(
                        TERMINAL_CAMPAIGN_STATES + IDLE_CAMPAIGN_STATES
                    ),
                    _campaign_not_purged(),
                )
                .with_for_update()
            )
            campaign = result.scalars().first()
            if campaign is None:
                return False

            await session.execute(
                update(QueuedRunModel)
                .where(QueuedRunModel.campaign_id == campaign.id)
                .values(context_variables={})
            )
            if campaign.state in IDLE_CAMPAIGN_STATES:
                campaign.state = "failed"
                campaign.logs = [
                    *(campaign.logs if isinstance(campaign.logs, list) else []),
                    {
                        "ts": purged_at.isoformat(),
                        "level": "info",
                        "event": "retention_expired",
                        "message": (
                            "The data retention period passed, so the contact "
                            "list was deleted and the campaign was closed."
                        ),
                    },
                ]
            metadata = (
                campaign.orchestrator_metadata
                if isinstance(campaign.orchestrator_metadata, dict)
                else {}
            )
            campaign.orchestrator_metadata = {
                **metadata,
                CAMPAIGN_PURGED_AT_KEY: purged_at.isoformat(),
            }
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return True

    async def scrub_finished_queued_runs_context(
        self,
        *,
        organization_id: int,
        created_before: datetime,
        limit: int = 500,
    ) -> int:
        """Clear the contact row of finished queued runs older than the cutoff.

        Covers long-running campaigns, whose rows from months ago would
        otherwise wait for the whole campaign to finish. Queued (not yet
        dialled) rows are left alone. Returns the number of rows cleared;
        call again until it returns less than ``limit``.
        """
        async with self.async_session() as session:
            batch = (
                select(QueuedRunModel.id)
                .join(CampaignModel, QueuedRunModel.campaign_id == CampaignModel.id)
                .where(
                    CampaignModel.organization_id == organization_id,
                    QueuedRunModel.state.in_(TERMINAL_QUEUED_RUN_STATES),
                    QueuedRunModel.created_at < created_before,
                    cast(QueuedRunModel.context_variables, Text) != "{}",
                )
                .order_by(QueuedRunModel.id)
                .limit(limit)
                .scalar_subquery()
            )
            result = await session.execute(
                update(QueuedRunModel)
                .where(QueuedRunModel.id.in_(batch))
                .values(context_variables={})
                .execution_options(synchronize_session=False)
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return result.rowcount or 0

    # --- embed sessions & webhook deliveries --------------------------------

    async def scrub_embed_session_visitor_data(
        self, *, created_before: datetime, limit: int = 1000
    ) -> int:
        """Null the visitor IP and user agent of widget sessions before the cutoff.

        Returns the number of rows cleared; call again until it returns less
        than ``limit``.
        """
        async with self.async_session() as session:
            batch = (
                select(EmbedSessionModel.id)
                .where(
                    EmbedSessionModel.created_at < created_before,
                    or_(
                        EmbedSessionModel.client_ip.is_not(None),
                        EmbedSessionModel.user_agent.is_not(None),
                    ),
                )
                .order_by(EmbedSessionModel.id)
                .limit(limit)
                .scalar_subquery()
            )
            result = await session.execute(
                update(EmbedSessionModel)
                .where(EmbedSessionModel.id.in_(batch))
                .values(client_ip=None, user_agent=None)
                .execution_options(synchronize_session=False)
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return result.rowcount or 0

    async def scrub_finished_webhook_delivery_payloads(
        self, *, created_before: datetime, limit: int = 1000
    ) -> int:
        """Clear payload and last error of finished deliveries before the cutoff.

        Only succeeded and dead-lettered rows: a pending row still needs its
        frozen payload for the next attempt. The rows themselves stay, as the
        per-run/per-node idempotency key that stops a re-run from sending a
        duplicate. Returns the number of rows cleared; call again until it
        returns less than ``limit``.
        """
        async with self.async_session() as session:
            batch = (
                select(WebhookDeliveryModel.id)
                .where(
                    WebhookDeliveryModel.status.in_(TERMINAL_WEBHOOK_DELIVERY_STATES),
                    WebhookDeliveryModel.created_at < created_before,
                    or_(
                        cast(WebhookDeliveryModel.payload, Text) != "{}",
                        WebhookDeliveryModel.last_error.is_not(None),
                    ),
                )
                .order_by(WebhookDeliveryModel.id)
                .limit(limit)
                .scalar_subquery()
            )
            result = await session.execute(
                update(WebhookDeliveryModel)
                .where(WebhookDeliveryModel.id.in_(batch))
                .values(payload={}, last_error=None)
                .execution_options(synchronize_session=False)
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return result.rowcount or 0

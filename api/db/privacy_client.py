"""Database access for data subject requests (GDPR Art. 15 and 17).

An organization answers its callers' requests through these: find every call
and campaign contact row for one phone number, export it, and erase it. Runs
are scrubbed with the retention purge's ``scrub_workflow_runs_call_content``
(not deleted), so billing and usage history keep their rows; this client adds
the lookups and the scrubs of what hangs off a run.

Every method is scoped to one organization: ``workflow_runs`` carries no
``organization_id``, so runs are reached through ``workflows.organization_id``
and queued runs through ``campaigns.organization_id``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Text,
    and_,
    case,
    cast,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.orm import aliased

from api.db.base_client import BaseDBClient
from api.db.models import (
    CampaignModel,
    EmbedSessionModel,
    EmbedTokenModel,
    QueuedRunModel,
    TelephonyPhoneNumberModel,
    WebhookDeliveryModel,
    WorkflowModel,
    WorkflowRunModel,
    WorkflowRunTextSessionModel,
)
from api.db.retention_client import (
    CAMPAIGN_PURGED_AT_KEY,
    WORKFLOW_RUN_PURGED_AT_KEY,
    ExpiredCampaign,
    ExpiredWorkflowRun,
)
from api.enums import CallType

# A queued run being dialled right now; its call is still to come.
QUEUED_RUN_IN_FLIGHT_STATE = "processing"


@dataclass(frozen=True)
class ErasableWorkflowRun:
    """A run of the organization and what deciding on its erasure needs."""

    objects: ExpiredWorkflowRun
    workflow_id: int
    is_completed: bool
    created_at: Optional[datetime]
    # Latest text-chat activity, for an open chat.
    chat_updated_at: Optional[datetime]
    purged: bool

    @property
    def id(self) -> int:
        return self.objects.id


@dataclass(frozen=True)
class SubjectWorkflowRun:
    """Everything stored about one call, for a data subject export."""

    id: int
    workflow_id: int
    workflow_name: str
    name: str
    created_at: Optional[datetime]
    call_type: str
    state: str
    is_completed: bool
    usage_info: dict[str, Any]
    initial_context: dict[str, Any]
    gathered_context: dict[str, Any]
    logs: dict[str, Any]
    annotations: dict[str, Any]
    recording_url: Optional[str]
    transcript_url: Optional[str]
    storage_backend: str
    extra: dict[str, Any]
    chat_session_data: Optional[dict[str, Any]]
    chat_updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class SubjectQueuedRun:
    id: int
    campaign_id: int
    campaign_name: str
    state: str
    created_at: Optional[datetime]
    scheduled_for: Optional[datetime]
    context_variables: dict[str, Any]


@dataclass(frozen=True)
class NumberPrefilter:
    """A coarse SQL filter for stored addresses that may equal one number.

    Stored addresses are not normalized, so SQL only narrows the rows down;
    the caller compares normalized addresses in Python. ``digits`` matches
    when the stored value's digits contain it; ``fragment`` when the
    lower-cased stored value contains it.
    """

    digits: Optional[str] = None
    fragment: Optional[str] = None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _matches_prefilter(column, prefilter: NumberPrefilter):
    """``column`` (a JSON text value) may hold the number."""
    if prefilter.digits:
        return func.regexp_replace(column, r"\D", "", "g").like(f"%{prefilter.digits}%")
    if prefilter.fragment:
        return func.lower(column).like(
            f"%{_escape_like(prefilter.fragment.lower())}%", escape="\\"
        )
    raise ValueError("A number prefilter needs digits or a fragment")


# The call-context keys that hold the other party's number, by direction.
# The rest hold the organization's own number (the line called, or the
# caller ID used), so they never identify the data subject.
INBOUND_COUNTERPART_KEYS = ("caller_number",)
OUTBOUND_COUNTERPART_KEYS = ("called_number", "phone_number")


def counterpart_keys(call_type: Optional[str]) -> tuple[str, ...]:
    return (
        INBOUND_COUNTERPART_KEYS
        if call_type == CallType.INBOUND.value
        else OUTBOUND_COUNTERPART_KEYS
    )


def _run_number_filter(prefilter: NumberPrefilter):
    def any_key(keys):
        return or_(
            *(
                _matches_prefilter(
                    WorkflowRunModel.initial_context[key].as_string(), prefilter
                )
                for key in keys
            )
        )

    inbound = WorkflowRunModel.call_type == CallType.INBOUND.value
    return or_(
        and_(inbound, any_key(INBOUND_COUNTERPART_KEYS)),
        and_(~inbound, any_key(OUTBOUND_COUNTERPART_KEYS)),
    )


def _run_purged():
    return WorkflowRunModel.extra[WORKFLOW_RUN_PURGED_AT_KEY].as_string().is_not(None)


class PrivacyClient(BaseDBClient):
    """Finds and erases one data subject's calls within an organization."""

    # --- workflow runs -----------------------------------------------------

    async def get_erasable_workflow_runs(
        self,
        *,
        organization_id: int,
        run_ids: list[int],
        workflow_id: Optional[int] = None,
    ) -> list[ErasableWorkflowRun]:
        """These runs, if they belong to the organization (and ``workflow_id``)."""
        if not run_ids:
            return []
        async with self.async_session() as session:
            query = (
                select(
                    WorkflowRunModel.id,
                    WorkflowRunModel.workflow_id,
                    WorkflowRunModel.recording_url,
                    WorkflowRunModel.transcript_url,
                    WorkflowRunModel.storage_backend,
                    WorkflowRunModel.extra,
                    WorkflowRunModel.is_completed,
                    WorkflowRunModel.created_at,
                    WorkflowRunTextSessionModel.updated_at.label("chat_updated_at"),
                    _run_purged().label("purged"),
                )
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .outerjoin(
                    WorkflowRunTextSessionModel,
                    WorkflowRunTextSessionModel.workflow_run_id == WorkflowRunModel.id,
                )
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.id.in_(run_ids),
                )
                .order_by(WorkflowRunModel.id)
            )
            if workflow_id is not None:
                query = query.where(WorkflowRunModel.workflow_id == workflow_id)
            result = await session.execute(query)
            return [
                ErasableWorkflowRun(
                    objects=ExpiredWorkflowRun(
                        id=row.id,
                        recording_url=row.recording_url,
                        transcript_url=row.transcript_url,
                        storage_backend=row.storage_backend,
                        extra=_as_dict(row.extra),
                    ),
                    workflow_id=row.workflow_id,
                    is_completed=bool(row.is_completed),
                    created_at=row.created_at,
                    chat_updated_at=row.chat_updated_at,
                    purged=bool(row.purged),
                )
                for row in result.all()
            ]

    async def find_workflow_run_number_candidates(
        self,
        *,
        organization_id: int,
        prefilter: NumberPrefilter,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[tuple[int, str, dict[str, Any]]]:
        """``(id, call_type, initial_context)`` of runs that may be with the number.

        Only the other party's side of the call context is searched (see
        ``counterpart_keys``).

        Keyset-paged by id. Runs whose content is already gone are skipped:
        their call context no longer names anyone.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    WorkflowRunModel.id,
                    WorkflowRunModel.call_type,
                    WorkflowRunModel.initial_context,
                )
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.id > after_id,
                    _run_number_filter(prefilter),
                )
                .order_by(WorkflowRunModel.id)
                .limit(limit)
            )
            return [
                (row.id, row.call_type, _as_dict(row.initial_context))
                for row in result.all()
            ]

    async def get_subject_workflow_runs(
        self, *, organization_id: int, run_ids: list[int]
    ) -> list[SubjectWorkflowRun]:
        if not run_ids:
            return []
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    WorkflowRunModel,
                    WorkflowModel.name.label("workflow_name"),
                    WorkflowRunTextSessionModel.session_data.label("chat_session_data"),
                    WorkflowRunTextSessionModel.updated_at.label("chat_updated_at"),
                )
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .outerjoin(
                    WorkflowRunTextSessionModel,
                    WorkflowRunTextSessionModel.workflow_run_id == WorkflowRunModel.id,
                )
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.id.in_(run_ids),
                )
                .order_by(WorkflowRunModel.created_at, WorkflowRunModel.id)
            )
            runs = []
            for run, workflow_name, chat_session_data, chat_updated_at in result.all():
                runs.append(
                    SubjectWorkflowRun(
                        id=run.id,
                        workflow_id=run.workflow_id,
                        workflow_name=workflow_name,
                        name=run.name,
                        created_at=run.created_at,
                        call_type=run.call_type,
                        state=run.state,
                        is_completed=bool(run.is_completed),
                        usage_info=_as_dict(run.usage_info),
                        initial_context=_as_dict(run.initial_context),
                        gathered_context=_as_dict(run.gathered_context),
                        logs=_as_dict(run.logs),
                        annotations=_as_dict(run.annotations),
                        recording_url=run.recording_url,
                        transcript_url=run.transcript_url,
                        storage_backend=run.storage_backend,
                        extra=_as_dict(run.extra),
                        chat_session_data=(
                            chat_session_data
                            if isinstance(chat_session_data, dict)
                            else None
                        ),
                        chat_updated_at=chat_updated_at,
                    )
                )
            return runs

    async def scrub_workflow_run_side_data(
        self, *, organization_id: int, run_ids: list[int]
    ) -> tuple[int, int]:
        """Clear what other tables keep about these runs.

        Webhook deliveries lose their frozen payload and error; one still
        pending is dead-lettered instead of being sent empty. Widget sessions
        lose the visitor's IP and user agent. Returns ``(webhook deliveries,
        embed sessions)`` cleared.
        """
        if not run_ids:
            return 0, 0
        owned_runs = (
            select(WorkflowRunModel.id)
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(
                WorkflowModel.organization_id == organization_id,
                WorkflowRunModel.id.in_(run_ids),
            )
        )
        async with self.async_session() as session:
            pending = WebhookDeliveryModel.status == "pending"
            deliveries = await session.execute(
                update(WebhookDeliveryModel)
                .where(
                    WebhookDeliveryModel.organization_id == organization_id,
                    WebhookDeliveryModel.workflow_run_id.in_(owned_runs),
                    or_(
                        cast(WebhookDeliveryModel.payload, Text) != "{}",
                        WebhookDeliveryModel.last_error.is_not(None),
                        pending,
                    ),
                )
                .values(
                    payload={},
                    last_error=None,
                    status=case(
                        (
                            pending,
                            literal("dead_letter", WebhookDeliveryModel.status.type),
                        ),
                        else_=WebhookDeliveryModel.status,
                    ),
                    scheduled_for=None,
                )
                .execution_options(synchronize_session=False)
            )
            sessions = await session.execute(
                update(EmbedSessionModel)
                .where(
                    EmbedSessionModel.workflow_run_id.in_(owned_runs),
                    EmbedSessionModel.embed_token_id.in_(
                        select(EmbedTokenModel.id).where(
                            EmbedTokenModel.organization_id == organization_id
                        )
                    ),
                    or_(
                        EmbedSessionModel.client_ip.is_not(None),
                        EmbedSessionModel.user_agent.is_not(None),
                    ),
                )
                .values(client_ip=None, user_agent=None)
                .execution_options(synchronize_session=False)
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return deliveries.rowcount or 0, sessions.rowcount or 0

    # --- the organization's own numbers -------------------------------------

    async def get_organization_phone_addresses(
        self, organization_id: int
    ) -> list[tuple[str, str, Optional[str]]]:
        """``(address, address_normalized, country_code)`` of the organization's numbers."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    TelephonyPhoneNumberModel.address,
                    TelephonyPhoneNumberModel.address_normalized,
                    TelephonyPhoneNumberModel.country_code,
                ).where(TelephonyPhoneNumberModel.organization_id == organization_id)
            )
            return [
                (row.address, row.address_normalized, row.country_code)
                for row in result.all()
            ]

    # --- campaign contact rows ----------------------------------------------

    async def find_queued_run_number_candidates(
        self,
        *,
        organization_id: int,
        prefilter: NumberPrefilter,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[SubjectQueuedRun]:
        """Queued runs whose ``phone_number`` may be the number, keyset-paged by id."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    QueuedRunModel.id,
                    QueuedRunModel.campaign_id,
                    CampaignModel.name.label("campaign_name"),
                    QueuedRunModel.state,
                    QueuedRunModel.created_at,
                    QueuedRunModel.scheduled_for,
                    QueuedRunModel.context_variables,
                )
                .join(CampaignModel, QueuedRunModel.campaign_id == CampaignModel.id)
                .where(
                    CampaignModel.organization_id == organization_id,
                    QueuedRunModel.id > after_id,
                    _matches_prefilter(
                        QueuedRunModel.context_variables["phone_number"].as_string(),
                        prefilter,
                    ),
                )
                .order_by(QueuedRunModel.id)
                .limit(limit)
            )
            return [
                SubjectQueuedRun(
                    id=row.id,
                    campaign_id=row.campaign_id,
                    campaign_name=row.campaign_name,
                    state=row.state,
                    created_at=row.created_at,
                    scheduled_for=row.scheduled_for,
                    context_variables=_as_dict(row.context_variables),
                )
                for row in result.all()
            ]

    async def erase_queued_runs(
        self, *, organization_id: int, queued_run_ids: list[int]
    ) -> tuple[int, int]:
        """Remove these campaign contact rows of the organization.

        A row still waiting to be dialled is deleted, so it is never called;
        if a run or a retry already points at it, it is failed instead. A
        dialled row keeps its place (it is the run's campaign link) with its
        contact data cleared. A row being dialled right now is left alone.
        Returns ``(deleted, cleared)``.
        """
        if not queued_run_ids:
            return 0, 0
        owned = (
            select(QueuedRunModel.id)
            .join(CampaignModel, QueuedRunModel.campaign_id == CampaignModel.id)
            .where(
                CampaignModel.organization_id == organization_id,
                QueuedRunModel.id.in_(queued_run_ids),
                QueuedRunModel.state != QUEUED_RUN_IN_FLIGHT_STATE,
            )
        )
        child = aliased(QueuedRunModel)
        referenced = or_(
            exists().where(WorkflowRunModel.queued_run_id == QueuedRunModel.id),
            exists().where(child.parent_queued_run_id == QueuedRunModel.id),
        )
        async with self.async_session() as session:
            deleted = await session.execute(
                delete(QueuedRunModel)
                .where(
                    QueuedRunModel.id.in_(owned),
                    QueuedRunModel.state == "queued",
                    ~referenced,
                )
                .execution_options(synchronize_session=False)
            )
            failed = await session.execute(
                update(QueuedRunModel)
                .where(QueuedRunModel.id.in_(owned), QueuedRunModel.state == "queued")
                .values(
                    state="failed",
                    context_variables={},
                    scheduled_for=None,
                    retry_reason="erased",
                )
                .execution_options(synchronize_session=False)
            )
            cleared = await session.execute(
                update(QueuedRunModel)
                .where(
                    QueuedRunModel.id.in_(owned),
                    cast(QueuedRunModel.context_variables, Text) != "{}",
                )
                .values(context_variables={})
                .execution_options(synchronize_session=False)
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return deleted.rowcount or 0, (failed.rowcount or 0) + (
                cleared.rowcount or 0
            )

    async def get_campaign_csv_sources(
        self, organization_id: int
    ) -> list[ExpiredCampaign]:
        """The organization's CSV campaigns whose contact list still exists."""
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
                    CampaignModel.source_type == "csv",
                    CampaignModel.orchestrator_metadata[CAMPAIGN_PURGED_AT_KEY]
                    .as_string()
                    .is_(None),
                )
                .order_by(CampaignModel.id)
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

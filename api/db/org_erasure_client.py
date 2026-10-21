"""Database access for organisation deletion (GDPR Art. 17).

An admin's request closes the organisation without losing anything: it
records when erasure is due and switches off what keeps working without a
signed-in user (API keys, widget tokens, agent triggers, active campaigns),
remembering exactly which ones so a cancel restores only those. Once the grace
period has passed the erasure service (``api/services/privacy``) deletes the
stored objects and then calls :meth:`OrgErasureClient.erase_organization_rows`,
which deletes every organisation-scoped row and leaves the organisation row as
a tombstone. Billing accounts, the credit ledger and usage cycles are kept:
they are accounting records with their own retention period.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.base_client import BaseDBClient
from api.db.models import (
    AgentTriggerModel,
    APIKeyModel,
    CampaignModel,
    EmbedTokenModel,
    ExternalCredentialModel,
    FolderModel,
    IntegrationModel,
    KnowledgeBaseChunkModel,
    KnowledgeBaseDocumentModel,
    OrganizationConfigurationModel,
    OrganizationInvitationModel,
    OrganizationModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    ToolModel,
    UserModel,
    WebhookDeliveryModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRecordingModel,
    WorkflowRunModel,
    organization_users_association,
)
from api.db.retention_client import ExpiredWorkflowRun
from api.db.skill_models import SkillModel
from api.enums import TriggerState

ERASED_ORGANIZATION_NAME = "Deleted organisation"

# Keys of ``organizations.deletion_suspended``.
SUSPENDED_API_KEYS = "api_key_ids"
SUSPENDED_EMBED_TOKENS = "embed_token_ids"
SUSPENDED_AGENT_TRIGGERS = "agent_trigger_ids"
SUSPENDED_CAMPAIGNS = "campaign_ids"
SUSPENDED_SYNCING_CAMPAIGNS = "syncing_campaign_ids"

# Campaigns that are dialling or about to (a syncing campaign turns running
# when its source sync finishes); the request pauses them.
ACTIVE_CAMPAIGN_STATES = ("syncing", "running")
PAUSED_CAMPAIGN_STATE = "paused"


@dataclass(frozen=True)
class OrganizationDeletionState:
    organization_id: int
    name: Optional[str]
    requested_at: Optional[datetime]
    scheduled_for: Optional[datetime]
    erased_at: Optional[datetime]

    @property
    def is_pending(self) -> bool:
        return self.requested_at is not None and self.erased_at is None

    @property
    def is_erased(self) -> bool:
        return self.erased_at is not None


@dataclass(frozen=True)
class PromptRecordingObject:
    """A prompt recording's stored audio, as recorded on its row."""

    id: int
    recording_id: str
    storage_key: str
    storage_backend: str


def _state(org: OrganizationModel) -> OrganizationDeletionState:
    return OrganizationDeletionState(
        organization_id=org.id,
        name=org.name,
        requested_at=org.deletion_requested_at,
        scheduled_for=org.deletion_scheduled_for,
        erased_at=org.erased_at,
    )


def _ids(suspended: Any, key: str) -> list[int]:
    if not isinstance(suspended, dict):
        return []
    values = suspended.get(key)
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, int) and not isinstance(v, bool)]


async def _lock_organization(
    session: AsyncSession, organization_id: int
) -> Optional[OrganizationModel]:
    result = await session.execute(
        select(OrganizationModel)
        .where(OrganizationModel.id == organization_id)
        .with_for_update()
    )
    return result.scalars().first()


def _organization_workflow_ids(organization_id: int):
    return select(WorkflowModel.id).where(
        WorkflowModel.organization_id == organization_id
    )


class OrgErasureClient(BaseDBClient):
    # --- status --------------------------------------------------------------

    async def get_organization_deletion_state(
        self, organization_id: int
    ) -> Optional[OrganizationDeletionState]:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(
                        OrganizationModel.id,
                        OrganizationModel.name,
                        OrganizationModel.deletion_requested_at,
                        OrganizationModel.deletion_scheduled_for,
                        OrganizationModel.erased_at,
                    ).where(OrganizationModel.id == organization_id)
                )
            ).first()
            if row is None:
                return None
            return OrganizationDeletionState(
                organization_id=row.id,
                name=row.name,
                requested_at=row.deletion_requested_at,
                scheduled_for=row.deletion_scheduled_for,
                erased_at=row.erased_at,
            )

    async def is_erased_organization_provider_id(self, provider_id: str) -> bool:
        """Whether an erased organisation had this provider id (e.g. a Stack team)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    exists().where(OrganizationModel.erased_provider_id == provider_id)
                )
            )
            return bool(result.scalar())

    # --- request and cancel --------------------------------------------------

    async def request_organization_deletion(
        self,
        organization_id: int,
        *,
        requested_at: datetime,
        scheduled_for: datetime,
    ) -> Optional[OrganizationDeletionState]:
        """Schedule erasure and switch off what runs without a signed-in user.

        Idempotent: a second request leaves the first schedule (and the record
        of what it switched off) untouched. Returns None if the organisation
        does not exist.
        """
        async with self.async_session() as session:
            org = await _lock_organization(session, organization_id)
            if org is None:
                return None
            if org.deletion_requested_at is not None or org.erased_at is not None:
                return _state(org)

            api_key_ids = (
                await session.execute(
                    update(APIKeyModel)
                    .where(
                        APIKeyModel.organization_id == organization_id,
                        APIKeyModel.is_active.is_(True),
                        APIKeyModel.archived_at.is_(None),
                    )
                    .values(is_active=False)
                    .returning(APIKeyModel.id)
                )
            ).scalars()
            api_key_ids = sorted(api_key_ids.all())
            embed_token_ids = (
                await session.execute(
                    update(EmbedTokenModel)
                    .where(
                        EmbedTokenModel.organization_id == organization_id,
                        EmbedTokenModel.is_active.is_(True),
                    )
                    .values(is_active=False, updated_at=requested_at)
                    .returning(EmbedTokenModel.id)
                )
            ).scalars()
            embed_token_ids = sorted(embed_token_ids.all())
            trigger_ids = (
                await session.execute(
                    update(AgentTriggerModel)
                    .where(
                        AgentTriggerModel.organization_id == organization_id,
                        AgentTriggerModel.state == TriggerState.ACTIVE.value,
                    )
                    .values(state=TriggerState.ARCHIVED.value)
                    .returning(AgentTriggerModel.id)
                )
            ).scalars()
            trigger_ids = sorted(trigger_ids.all())
            active = (
                await session.execute(
                    select(CampaignModel.id, CampaignModel.state)
                    .where(
                        CampaignModel.organization_id == organization_id,
                        CampaignModel.state.in_(ACTIVE_CAMPAIGN_STATES),
                    )
                    .with_for_update()
                )
            ).all()
            campaign_ids = sorted(row.id for row in active if row.state == "running")
            syncing_campaign_ids = sorted(
                row.id for row in active if row.state == "syncing"
            )
            if active:
                await session.execute(
                    update(CampaignModel)
                    .where(CampaignModel.id.in_([row.id for row in active]))
                    .values(state=PAUSED_CAMPAIGN_STATE, updated_at=requested_at)
                )

            org.deletion_requested_at = requested_at
            org.deletion_scheduled_for = scheduled_for
            org.deletion_suspended = {
                SUSPENDED_API_KEYS: api_key_ids,
                SUSPENDED_EMBED_TOKENS: embed_token_ids,
                SUSPENDED_AGENT_TRIGGERS: trigger_ids,
                SUSPENDED_CAMPAIGNS: campaign_ids,
                SUSPENDED_SYNCING_CAMPAIGNS: syncing_campaign_ids,
            }
            state = _state(org)
            await session.commit()
            return state

    async def cancel_organization_deletion(
        self, organization_id: int, *, cancelled_at: datetime
    ) -> Optional[OrganizationDeletionState]:
        """Undo a pending request, restoring only what the request switched off.

        Returns the new state, or None when there was nothing to cancel (no
        request, or the organisation was already erased).
        """
        async with self.async_session() as session:
            org = await _lock_organization(session, organization_id)
            if org is None or org.deletion_requested_at is None or org.erased_at:
                return None
            suspended = org.deletion_suspended

            api_key_ids = _ids(suspended, SUSPENDED_API_KEYS)
            if api_key_ids:
                # A key archived since (its creator left) stays off.
                await session.execute(
                    update(APIKeyModel)
                    .where(
                        APIKeyModel.organization_id == organization_id,
                        APIKeyModel.id.in_(api_key_ids),
                        APIKeyModel.archived_at.is_(None),
                    )
                    .values(is_active=True)
                )
            embed_token_ids = _ids(suspended, SUSPENDED_EMBED_TOKENS)
            if embed_token_ids:
                await session.execute(
                    update(EmbedTokenModel)
                    .where(
                        EmbedTokenModel.organization_id == organization_id,
                        EmbedTokenModel.id.in_(embed_token_ids),
                    )
                    .values(is_active=True, updated_at=cancelled_at)
                )
            trigger_ids = _ids(suspended, SUSPENDED_AGENT_TRIGGERS)
            if trigger_ids:
                await session.execute(
                    update(AgentTriggerModel)
                    .where(
                        AgentTriggerModel.organization_id == organization_id,
                        AgentTriggerModel.id.in_(trigger_ids),
                        AgentTriggerModel.state == TriggerState.ARCHIVED.value,
                    )
                    .values(state=TriggerState.ACTIVE.value)
                )
            campaign_ids = _ids(suspended, SUSPENDED_CAMPAIGNS)
            if campaign_ids:
                await session.execute(
                    update(CampaignModel)
                    .where(
                        CampaignModel.organization_id == organization_id,
                        CampaignModel.id.in_(campaign_ids),
                        CampaignModel.state == PAUSED_CAMPAIGN_STATE,
                    )
                    .values(state="running", updated_at=cancelled_at)
                )
            syncing_ids = _ids(suspended, SUSPENDED_SYNCING_CAMPAIGNS)
            if syncing_ids:
                # A sync that finished meanwhile left the campaign paused (see
                # complete_campaign_source_sync): start it; one still under way
                # starts it itself when it finishes.
                for synced, state in ((True, "running"), (False, "syncing")):
                    sync_done = CampaignModel.source_sync_status == "completed"
                    await session.execute(
                        update(CampaignModel)
                        .where(
                            CampaignModel.organization_id == organization_id,
                            CampaignModel.id.in_(syncing_ids),
                            CampaignModel.state == PAUSED_CAMPAIGN_STATE,
                            sync_done if synced else ~sync_done,
                        )
                        .values(state=state, updated_at=cancelled_at)
                    )

            org.deletion_requested_at = None
            org.deletion_scheduled_for = None
            org.deletion_suspended = None
            state = _state(org)
            await session.commit()
            return state

    # --- erasure -------------------------------------------------------------

    async def get_organizations_due_for_erasure(
        self, *, now: datetime, after_id: int = 0, limit: int = 100
    ) -> list[int]:
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel.id)
                .where(
                    OrganizationModel.deletion_requested_at.is_not(None),
                    OrganizationModel.deletion_scheduled_for <= now,
                    OrganizationModel.erased_at.is_(None),
                    OrganizationModel.id > after_id,
                )
                .order_by(OrganizationModel.id)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_organization_workflow_runs_for_erasure(
        self, organization_id: int, *, limit: int = 100
    ) -> list[ExpiredWorkflowRun]:
        """The organisation's oldest remaining runs, with their object keys."""
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
                .where(WorkflowModel.organization_id == organization_id)
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

    async def delete_organization_workflow_runs(
        self, organization_id: int, run_ids: list[int]
    ) -> int:
        """Delete these runs of the organisation (and their sessions and
        webhook deliveries, by cascade). Ledger entries keep their amounts and
        lose only the run reference."""
        if not run_ids:
            return 0
        async with self.async_session() as session:
            result = await session.execute(
                delete(WorkflowRunModel).where(
                    WorkflowRunModel.id.in_(run_ids),
                    WorkflowRunModel.workflow_id.in_(
                        _organization_workflow_ids(organization_id)
                    ),
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def get_organization_prompt_recordings(
        self, organization_id: int
    ) -> list[PromptRecordingObject]:
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    WorkflowRecordingModel.id,
                    WorkflowRecordingModel.recording_id,
                    WorkflowRecordingModel.storage_key,
                    WorkflowRecordingModel.storage_backend,
                )
                .where(WorkflowRecordingModel.organization_id == organization_id)
                .order_by(WorkflowRecordingModel.id)
            )
            return [
                PromptRecordingObject(
                    id=row.id,
                    recording_id=row.recording_id,
                    storage_key=row.storage_key,
                    storage_backend=row.storage_backend,
                )
                for row in result.all()
            ]

    async def erase_organization_rows(
        self, organization_id: int, *, erased_at: datetime
    ) -> bool:
        """Delete every row of the organisation and tombstone it, in one
        transaction.

        Call only once its stored objects are gone. Refuses (returns False)
        while the organisation still has workflow runs, since their objects
        are deleted run by run first, or when the request was cancelled.
        Returns True when the organisation is erased (now or before).
        """
        async with self.async_session() as session:
            org = await _lock_organization(session, organization_id)
            if org is None:
                return False
            if org.erased_at is not None:
                return True
            if org.deletion_requested_at is None:
                return False
            has_runs = (
                await session.execute(
                    select(
                        exists().where(
                            WorkflowRunModel.workflow_id.in_(
                                _organization_workflow_ids(organization_id)
                            )
                        )
                    )
                )
            ).scalar()
            if has_runs:
                return False

            members = organization_users_association
            workflow_ids = _organization_workflow_ids(organization_id)
            # Members with another organization move to one, preferring the
            # oldest that is not itself pending deletion (never an erased
            # one); the rest are left without one.
            other = OrganizationModel.__table__.alias("other_organization")
            other_membership = (
                select(members.c.organization_id)
                .join(other, other.c.id == members.c.organization_id)
                .where(
                    members.c.user_id == UserModel.id,
                    members.c.organization_id != organization_id,
                    other.c.erased_at.is_(None),
                )
                .order_by(
                    other.c.deletion_requested_at.is_not(None),
                    members.c.organization_id,
                )
                .limit(1)
                .scalar_subquery()
            )
            statements = [
                update(UserModel)
                .where(UserModel.selected_organization_id == organization_id)
                .values(selected_organization_id=other_membership)
                .execution_options(synchronize_session=False),
                members.delete().where(members.c.organization_id == organization_id),
                delete(OrganizationInvitationModel).where(
                    OrganizationInvitationModel.organization_id == organization_id
                ),
                delete(APIKeyModel).where(
                    APIKeyModel.organization_id == organization_id
                ),
                delete(EmbedTokenModel).where(
                    EmbedTokenModel.organization_id == organization_id
                ),
                delete(AgentTriggerModel).where(
                    AgentTriggerModel.organization_id == organization_id
                ),
                delete(WebhookDeliveryModel).where(
                    WebhookDeliveryModel.organization_id == organization_id
                ),
                # Queued runs (the contact lists) go with their campaigns.
                delete(CampaignModel).where(
                    CampaignModel.organization_id == organization_id
                ),
                # Phone numbers and trunks go with their configurations.
                delete(TelephonyConfigurationModel).where(
                    TelephonyConfigurationModel.organization_id == organization_id
                ),
                delete(TelephonyPhoneNumberModel).where(
                    TelephonyPhoneNumberModel.organization_id == organization_id
                ),
                update(WorkflowModel)
                .where(WorkflowModel.organization_id == organization_id)
                .values(released_definition_id=None),
                delete(WorkflowDefinitionModel).where(
                    WorkflowDefinitionModel.workflow_id.in_(workflow_ids)
                ),
                delete(WorkflowRecordingModel).where(
                    WorkflowRecordingModel.organization_id == organization_id
                ),
                delete(WorkflowModel).where(
                    WorkflowModel.organization_id == organization_id
                ),
                delete(FolderModel).where(
                    FolderModel.organization_id == organization_id
                ),
                delete(IntegrationModel).where(
                    IntegrationModel.organization_id == organization_id
                ),
                delete(ToolModel).where(ToolModel.organization_id == organization_id),
                delete(ExternalCredentialModel).where(
                    ExternalCredentialModel.organization_id == organization_id
                ),
                delete(KnowledgeBaseChunkModel).where(
                    KnowledgeBaseChunkModel.organization_id == organization_id
                ),
                delete(KnowledgeBaseDocumentModel).where(
                    KnowledgeBaseDocumentModel.organization_id == organization_id
                ),
                delete(SkillModel).where(SkillModel.organization_id == organization_id),
                delete(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id
                ),
            ]
            try:
                for statement in statements:
                    await session.execute(statement)
                org.erased_provider_id = org.provider_id
                org.provider_id = f"deleted_{organization_id}"
                org.name = ERASED_ORGANIZATION_NAME
                org.erased_at = erased_at
                org.deletion_suspended = None
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return True

"""Seed a fully populated organisation for the deletion and export tests."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    AgentTriggerModel,
    APIKeyModel,
    BillingAccountModel,
    BillingLedgerEntryModel,
    CampaignModel,
    EmbedSessionModel,
    EmbedTokenModel,
    ExternalCredentialModel,
    FolderModel,
    IntegrationModel,
    KnowledgeBaseChunkModel,
    KnowledgeBaseDocumentModel,
    OrganizationConfigurationModel,
    OrganizationInvitationModel,
    OrganizationModel,
    OrganizationUsageCycleModel,
    QueuedRunModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    ToolModel,
    UserConfigurationModel,
    UserModel,
    WebhookDeliveryModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRecordingModel,
    WorkflowRunModel,
    WorkflowRunTextSessionModel,
    organization_users_association,
)
from api.db.skill_models import SkillModel
from api.enums import OrgRole

SECRET = "sk-live-super-secret-value-1234"


class FakeStorage:
    """In-memory object store recording what was deleted."""

    def __init__(self):
        self.objects: set[str] = set()
        self.deleted_files: list[str] = []
        self.deleted_prefixes: list[str] = []
        self.failing: set[str] = set()

    def add(self, *keys: str) -> None:
        self.objects.update(keys)

    async def adelete_file(self, file_path: str) -> bool:
        self.deleted_files.append(file_path)
        if file_path in self.failing:
            return False
        self.objects.discard(file_path)
        return True

    async def adelete_prefix(self, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        keys = [key for key in self.objects if key.startswith(prefix)]
        self.objects.difference_update(keys)
        return len(keys)


def run_object_keys(run_id: int) -> set[str]:
    return {
        f"recordings/{run_id}.wav",
        f"recordings/{run_id}/user.wav",
        f"recordings/{run_id}/bot.wav",
        f"recordings/{run_id}/noveum/user/seg-1.wav",
        f"transcripts/{run_id}.txt",
    }


@dataclass
class SeededOrg:
    org: OrganizationModel
    admin: UserModel
    developer: UserModel
    workflow: WorkflowModel
    run: WorkflowRunModel
    api_key: APIKeyModel
    disabled_api_key: APIKeyModel
    embed_token: EmbedTokenModel
    disabled_embed_token: EmbedTokenModel
    trigger: AgentTriggerModel
    archived_trigger: AgentTriggerModel
    campaign: CampaignModel
    finished_campaign: CampaignModel
    billing_account: BillingAccountModel
    ledger_entry: BillingLedgerEntryModel
    usage_cycle: OrganizationUsageCycleModel
    phone_number: TelephonyPhoneNumberModel
    objects: set[str] = field(default_factory=set)


async def add_member(
    session: AsyncSession, user: UserModel, org: OrganizationModel, role: OrgRole
) -> None:
    await session.execute(
        organization_users_association.insert().values(
            user_id=user.id, organization_id=org.id, role=role.value
        )
    )


async def make_user(
    session: AsyncSession, org: OrganizationModel | None = None, *, email=None
) -> UserModel:
    tag = uuid.uuid4().hex[:10]
    user = UserModel(
        provider_id=f"privacy-{tag}",
        email=email or f"{tag}@example.test",
        name=f"User {tag}",
        password_hash="$argon2id$hash-must-never-leave",
        google_sub=f"google-{tag}",
        selected_organization_id=org.id if org else None,
    )
    session.add(user)
    await session.flush()
    return user


async def seed_organization(
    session: AsyncSession, storage: FakeStorage, *, name: str = "Acme Ltd"
) -> SeededOrg:
    now = datetime.now(UTC)
    org = OrganizationModel(provider_id=f"org_{uuid.uuid4().hex}", name=name)
    session.add(org)
    await session.flush()
    admin = await make_user(session, org)
    developer = await make_user(session, org)
    await add_member(session, admin, org, OrgRole.ADMIN)
    await add_member(session, developer, org, OrgRole.DEVELOPER)
    session.add(
        UserConfigurationModel(
            user_id=admin.id, key="ONBOARDING", configuration={"dismissed": True}
        )
    )

    folder = FolderModel(organization_id=org.id, name="Sales")
    session.add(folder)
    await session.flush()
    workflow = WorkflowModel(
        name="Receptionist",
        user_id=developer.id,
        organization_id=org.id,
        folder_id=folder.id,
        workflow_definition={"nodes": [], "edges": []},
    )
    session.add(workflow)
    await session.flush()
    definition = WorkflowDefinitionModel(
        workflow_id=workflow.id,
        workflow_json={"nodes": [], "edges": []},
        is_current=True,
        workflow_configurations={
            "model_overrides": {"llm": {"provider": "openai", "api_key": SECRET}}
        },
    )
    session.add(definition)
    await session.flush()
    workflow.released_definition_id = definition.id

    run = WorkflowRunModel(
        name="call",
        workflow_id=workflow.id,
        definition_id=definition.id,
        mode="twilio",
        storage_backend="minio",
        initial_context={"caller_number": "+353870000001"},
        is_completed=True,
        state="completed",
    )
    session.add(run)
    await session.flush()
    run.recording_url = f"recordings/{run.id}.wav"
    run.transcript_url = f"transcripts/{run.id}.txt"
    session.add(
        WorkflowRunTextSessionModel(
            workflow_run_id=run.id, session_data={"messages": []}, checkpoint={}
        )
    )
    session.add(
        WebhookDeliveryModel(
            workflow_run_id=run.id,
            organization_id=org.id,
            webhook_node_id="n1",
            payload={"caller": "+353870000001"},
            endpoint_url="https://hooks.example.test",
        )
    )

    api_key = APIKeyModel(
        organization_id=org.id,
        name="Live",
        key_hash=uuid.uuid4().hex,
        key_prefix="dgr_live",
        is_active=True,
        created_by=developer.id,
    )
    disabled_api_key = APIKeyModel(
        organization_id=org.id,
        name="Off",
        key_hash=uuid.uuid4().hex,
        key_prefix="dgr_off_",
        is_active=False,
        created_by=developer.id,
    )
    embed_token = EmbedTokenModel(
        token=f"emb-{uuid.uuid4().hex}",
        workflow_id=workflow.id,
        organization_id=org.id,
        created_by=developer.id,
        is_active=True,
    )
    disabled_embed_token = EmbedTokenModel(
        token=f"emb-{uuid.uuid4().hex}",
        workflow_id=workflow.id,
        organization_id=org.id,
        created_by=developer.id,
        is_active=False,
    )
    trigger = AgentTriggerModel(
        trigger_path=str(uuid.uuid4()),
        workflow_id=workflow.id,
        organization_id=org.id,
        state="active",
    )
    archived_trigger = AgentTriggerModel(
        trigger_path=str(uuid.uuid4()),
        workflow_id=workflow.id,
        organization_id=org.id,
        state="archived",
    )
    session.add_all(
        [
            api_key,
            disabled_api_key,
            embed_token,
            disabled_embed_token,
            trigger,
            archived_trigger,
        ]
    )
    await session.flush()
    session.add(
        EmbedSessionModel(
            session_token=uuid.uuid4().hex,
            embed_token_id=embed_token.id,
            workflow_run_id=run.id,
            client_ip="203.0.113.9",
            expires_at=now + timedelta(hours=1),
        )
    )

    telephony = TelephonyConfigurationModel(
        organization_id=org.id,
        name="Twilio",
        provider="twilio",
        credentials={"account_sid": "AC123", "auth_token": SECRET},
    )
    session.add(telephony)
    await session.flush()
    phone_number = TelephonyPhoneNumberModel(
        organization_id=org.id,
        telephony_configuration_id=telephony.id,
        address="+35315550100",
        address_normalized="+35315550100",
        address_type="pstn",
        inbound_workflow_id=workflow.id,
    )
    session.add(phone_number)

    campaign_csv = f"campaigns/{org.id}/{uuid.uuid4()}_contacts.csv"
    campaign = CampaignModel(
        name="Renewals",
        organization_id=org.id,
        workflow_id=workflow.id,
        created_by=developer.id,
        telephony_configuration_id=telephony.id,
        source_type="csv",
        source_id=campaign_csv,
        state="running",
    )
    finished_campaign = CampaignModel(
        name="Old",
        organization_id=org.id,
        workflow_id=workflow.id,
        created_by=developer.id,
        source_type="csv",
        source_id=campaign_csv,
        state="completed",
    )
    session.add_all([campaign, finished_campaign])
    await session.flush()
    session.add(
        QueuedRunModel(
            campaign_id=campaign.id,
            source_uuid="row-1",
            context_variables={"phone_number": "+353870000002"},
            state="queued",
        )
    )

    document = KnowledgeBaseDocumentModel(
        organization_id=org.id,
        filename="faq.pdf",
        created_by=developer.id,
    )
    session.add(document)
    await session.flush()
    session.add(
        KnowledgeBaseChunkModel(
            document_id=document.id,
            organization_id=org.id,
            chunk_text="Opening hours are 9 to 5",
            chunk_index=0,
            embedding_model="test-embedding",
            embedding_dimension=1536,
        )
    )
    recording_key = f"recordings/{org.id}/Greet0001/greeting.wav"
    session.add(
        WorkflowRecordingModel(
            recording_id="Greet0001",
            workflow_id=workflow.id,
            organization_id=org.id,
            transcript="Hello and welcome",
            storage_key=recording_key,
            storage_backend="minio",
            created_by=developer.id,
        )
    )
    session.add(
        ToolModel(
            organization_id=org.id,
            name="CRM lookup",
            definition={
                "config": {
                    "url": "https://crm.example.test",
                    "headers": {"Authorization": f"Bearer {SECRET}"},
                }
            },
            created_by=developer.id,
        )
    )
    session.add(
        ExternalCredentialModel(
            organization_id=org.id,
            name="CRM key",
            credential_type="api_key",
            credential_data={"header_name": "X-API-Key", "api_key": SECRET},
            created_by=developer.id,
        )
    )
    session.add(
        IntegrationModel(
            integration_id=uuid.uuid4().hex,
            organization_id=org.id,
            provider="slack",
            created_by=developer.id,
            connection_details={"access_token": SECRET},
        )
    )
    session.add(
        OrganizationConfigurationModel(
            organization_id=org.id,
            key="LANGFUSE_CREDENTIALS",
            value={"public_key": "pk", "secret_key": SECRET},
        )
    )
    session.add(
        OrganizationInvitationModel(
            organization_id=org.id,
            email="invitee@example.test",
            role="viewer",
            token_hash=uuid.uuid4().hex,
            invited_by=admin.id,
            expires_at=now + timedelta(days=7),
        )
    )
    session.add(
        SkillModel(
            organization_id=org.id,
            name=f"skill-{uuid.uuid4().hex[:6]}",
            description="d",
            body_md="b",
            created_by=developer.id,
        )
    )

    billing_account = BillingAccountModel(organization_id=org.id)
    session.add(billing_account)
    ledger_entry = BillingLedgerEntryModel(
        organization_id=org.id,
        entry_type="usage",
        amount_eur=Decimal("-1.2000"),
        balance_after_eur=Decimal("8.8000"),
        workflow_run_id=run.id,
        description="Call",
    )
    session.add(ledger_entry)
    usage_cycle = OrganizationUsageCycleModel(
        organization_id=org.id,
        period_start=now - timedelta(days=10),
        period_end=now + timedelta(days=20),
        quota_dograh_tokens=0,
    )
    session.add(usage_cycle)
    await session.flush()

    objects = run_object_keys(run.id) | {
        recording_key,
        campaign_csv,
        f"knowledge_base/{org.id}/{document.document_uuid}/faq.pdf",
        f"ambient-noise/{org.id}/{workflow.id}/cafe.wav",
    }
    storage.add(*objects)
    return SeededOrg(
        org=org,
        admin=admin,
        developer=developer,
        workflow=workflow,
        run=run,
        api_key=api_key,
        disabled_api_key=disabled_api_key,
        embed_token=embed_token,
        disabled_embed_token=disabled_embed_token,
        trigger=trigger,
        archived_trigger=archived_trigger,
        campaign=campaign,
        finished_campaign=finished_campaign,
        billing_account=billing_account,
        ledger_entry=ledger_entry,
        usage_cycle=usage_cycle,
        phone_number=phone_number,
        objects=objects,
    )

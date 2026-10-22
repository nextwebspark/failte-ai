"""Database reads for data exports (GDPR Art. 15 and 20).

Every query names its columns explicitly: an export carries what a person or
an organisation has put into the product, never credentials, password hashes,
provider tokens or call content. New secret-bearing columns therefore stay out
of exports until someone adds them here on purpose. Rows come back as plain
dicts; the export service (``api/services/privacy/data_export.py``) masks the
few JSON documents that can embed secrets and assembles the download.
"""

from typing import Any, Optional

from sqlalchemy import or_, select

from api.db.base_client import BaseDBClient
from api.db.models import (
    AgentTriggerModel,
    APIKeyModel,
    BillingAccountModel,
    BillingLedgerEntryModel,
    CampaignModel,
    EmbedTokenModel,
    ExternalCredentialModel,
    FolderModel,
    IntegrationModel,
    KnowledgeBaseDocumentModel,
    OrganizationInvitationModel,
    OrganizationModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    ToolModel,
    UserModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRecordingModel,
)


def _rows(result) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in result.all()]


class DataExportClient(BaseDBClient):
    async def export_user_profile(self, user_id: int) -> Optional[dict[str, Any]]:
        """The user's own profile, without credentials."""
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(
                        UserModel.id,
                        UserModel.email,
                        UserModel.name,
                        UserModel.avatar_url,
                        UserModel.created_at,
                        UserModel.email_verified_at,
                        UserModel.selected_organization_id,
                        UserModel.password_hash.is_not(None).label("has_password"),
                        UserModel.google_sub.is_not(None).label(
                            "google_sign_in_linked"
                        ),
                    ).where(UserModel.id == user_id)
                )
            ).first()
            return dict(row._mapping) if row else None

    async def export_organization_records(
        self, organization_id: int
    ) -> dict[str, list[dict[str, Any]]]:
        """Everything the organisation keeps in the product, by kind, minus
        secrets and call content. All reads are scoped to ``organization_id``."""
        org_workflows = select(WorkflowModel.id).where(
            WorkflowModel.organization_id == organization_id
        )
        queries = {
            "organization": select(
                OrganizationModel.id,
                OrganizationModel.name,
                OrganizationModel.created_at,
                OrganizationModel.deletion_requested_at,
                OrganizationModel.deletion_scheduled_for,
            ).where(OrganizationModel.id == organization_id),
            "invitations": select(
                OrganizationInvitationModel.email,
                OrganizationInvitationModel.role,
                OrganizationInvitationModel.created_at,
                OrganizationInvitationModel.expires_at,
                OrganizationInvitationModel.accepted_at,
                OrganizationInvitationModel.revoked_at,
            )
            .where(OrganizationInvitationModel.organization_id == organization_id)
            .order_by(OrganizationInvitationModel.id),
            "folders": select(FolderModel.id, FolderModel.name, FolderModel.created_at)
            .where(FolderModel.organization_id == organization_id)
            .order_by(FolderModel.id),
            "workflows": select(
                WorkflowModel.id,
                WorkflowModel.workflow_uuid,
                WorkflowModel.name,
                WorkflowModel.status,
                WorkflowModel.folder_id,
                WorkflowModel.created_at,
                WorkflowModel.released_definition_id,
            )
            .where(WorkflowModel.organization_id == organization_id)
            .order_by(WorkflowModel.id),
            # The draft (is_current) and the released version of each agent.
            "workflow_definitions": select(
                WorkflowDefinitionModel.id,
                WorkflowDefinitionModel.workflow_id,
                WorkflowDefinitionModel.status,
                WorkflowDefinitionModel.version_number,
                WorkflowDefinitionModel.is_current,
                WorkflowDefinitionModel.published_at,
                WorkflowDefinitionModel.created_at,
                WorkflowDefinitionModel.workflow_json,
                WorkflowDefinitionModel.workflow_configurations,
                WorkflowDefinitionModel.template_context_variables,
            )
            .where(
                WorkflowDefinitionModel.workflow_id.in_(org_workflows),
                or_(
                    WorkflowDefinitionModel.is_current.is_(True),
                    WorkflowDefinitionModel.id.in_(
                        select(WorkflowModel.released_definition_id).where(
                            WorkflowModel.organization_id == organization_id
                        )
                    ),
                ),
            )
            .order_by(WorkflowDefinitionModel.id),
            "tools": select(
                ToolModel.tool_uuid,
                ToolModel.name,
                ToolModel.description,
                ToolModel.category,
                ToolModel.status,
                ToolModel.definition,
                ToolModel.created_at,
            )
            .where(ToolModel.organization_id == organization_id)
            .order_by(ToolModel.id),
            "credentials": select(
                ExternalCredentialModel.credential_uuid,
                ExternalCredentialModel.name,
                ExternalCredentialModel.description,
                ExternalCredentialModel.credential_type,
                ExternalCredentialModel.created_at,
            )
            .where(ExternalCredentialModel.organization_id == organization_id)
            .order_by(ExternalCredentialModel.id),
            "integrations": select(
                IntegrationModel.provider,
                IntegrationModel.action,
                IntegrationModel.is_active,
                IntegrationModel.created_at,
            )
            .where(IntegrationModel.organization_id == organization_id)
            .order_by(IntegrationModel.id),
            "campaigns": select(
                CampaignModel.id,
                CampaignModel.name,
                CampaignModel.workflow_id,
                CampaignModel.state,
                CampaignModel.source_type,
                CampaignModel.total_rows,
                CampaignModel.processed_rows,
                CampaignModel.failed_rows,
                CampaignModel.created_at,
                CampaignModel.started_at,
                CampaignModel.completed_at,
            )
            .where(CampaignModel.organization_id == organization_id)
            .order_by(CampaignModel.id),
            "knowledge_base_documents": select(
                KnowledgeBaseDocumentModel.document_uuid,
                KnowledgeBaseDocumentModel.filename,
                KnowledgeBaseDocumentModel.file_size_bytes,
                KnowledgeBaseDocumentModel.mime_type,
                KnowledgeBaseDocumentModel.source_url,
                KnowledgeBaseDocumentModel.processing_status,
                KnowledgeBaseDocumentModel.is_active,
                KnowledgeBaseDocumentModel.created_at,
            )
            .where(KnowledgeBaseDocumentModel.organization_id == organization_id)
            .order_by(KnowledgeBaseDocumentModel.id),
            "prompt_recordings": select(
                WorkflowRecordingModel.recording_id,
                WorkflowRecordingModel.workflow_id,
                WorkflowRecordingModel.transcript,
                WorkflowRecordingModel.is_active,
                WorkflowRecordingModel.created_at,
            )
            .where(WorkflowRecordingModel.organization_id == organization_id)
            .order_by(WorkflowRecordingModel.id),
            "telephony_configurations": select(
                TelephonyConfigurationModel.id,
                TelephonyConfigurationModel.name,
                TelephonyConfigurationModel.provider,
                TelephonyConfigurationModel.is_default_outbound,
                TelephonyConfigurationModel.inactive,
                TelephonyConfigurationModel.created_at,
            )
            .where(TelephonyConfigurationModel.organization_id == organization_id)
            .order_by(TelephonyConfigurationModel.id),
            "phone_numbers": select(
                TelephonyPhoneNumberModel.address,
                TelephonyPhoneNumberModel.address_type,
                TelephonyPhoneNumberModel.country_code,
                TelephonyPhoneNumberModel.label,
                TelephonyPhoneNumberModel.telephony_configuration_id,
                TelephonyPhoneNumberModel.inbound_workflow_id,
                TelephonyPhoneNumberModel.is_active,
                TelephonyPhoneNumberModel.is_default_caller_id,
                TelephonyPhoneNumberModel.created_at,
            )
            .where(TelephonyPhoneNumberModel.organization_id == organization_id)
            .order_by(TelephonyPhoneNumberModel.id),
            "widget_tokens": select(
                EmbedTokenModel.workflow_id,
                EmbedTokenModel.allowed_domains,
                EmbedTokenModel.is_active,
                EmbedTokenModel.usage_count,
                EmbedTokenModel.usage_limit,
                EmbedTokenModel.expires_at,
                EmbedTokenModel.created_at,
            )
            .where(EmbedTokenModel.organization_id == organization_id)
            .order_by(EmbedTokenModel.id),
            "agent_triggers": select(
                AgentTriggerModel.workflow_id,
                AgentTriggerModel.state,
                AgentTriggerModel.created_at,
            )
            .where(AgentTriggerModel.organization_id == organization_id)
            .order_by(AgentTriggerModel.id),
            "api_keys": select(
                APIKeyModel.name,
                APIKeyModel.key_prefix,
                APIKeyModel.is_active,
                APIKeyModel.created_at,
                APIKeyModel.last_used_at,
                APIKeyModel.archived_at,
            )
            .where(APIKeyModel.organization_id == organization_id)
            .order_by(APIKeyModel.id),
            "billing_account": select(
                BillingAccountModel.plan,
                BillingAccountModel.balance_eur,
                BillingAccountModel.credit_limit_eur,
                BillingAccountModel.price_per_minute_eur,
                BillingAccountModel.created_at,
            ).where(BillingAccountModel.organization_id == organization_id),
            "billing_ledger": select(
                BillingLedgerEntryModel.entry_type,
                BillingLedgerEntryModel.amount_eur,
                BillingLedgerEntryModel.balance_after_eur,
                BillingLedgerEntryModel.description,
                BillingLedgerEntryModel.workflow_run_id,
                BillingLedgerEntryModel.created_at,
            )
            .where(BillingLedgerEntryModel.organization_id == organization_id)
            .order_by(BillingLedgerEntryModel.id),
        }
        async with self.async_session() as session:
            return {
                name: _rows(await session.execute(query))
                for name, query in queries.items()
            }

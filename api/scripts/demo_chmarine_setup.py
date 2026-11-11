"""The database side of the CH Marine demo (``api/scripts/demo_chmarine.py``):
the price-list document, the sample orders, the order-lookup tool and the
agent's own instructions. Called by the demo seed; every step is idempotent
and only ever runs on a marked demo workspace."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import or_, select

from api.db import db_client
from api.db.models import UserModel, WorkflowDefinitionModel, WorkflowModel
from api.scripts import demo_chmarine as chm
from api.services import demo_orders
from api.services.knowledge_base_keys import knowledge_base_document_prefix
from api.services.storage import storage_fs

# What happened to the price list on this run, for the seed's report.
LAST_RUN: dict[str, Any] = {}


async def _price_list_document(
    organization_id: int, owner: UserModel
) -> tuple[str | None, str]:
    """The price-list document's uuid, uploading and indexing it when it is
    missing or its text changed. Indexed for vector search (chunked) with
    the platform's embeddings; if that fails, kept as a full document, which
    the same search tool returns whole. Returns (uuid, how it is searched)."""
    from api.tasks.knowledge_base_processing import process_knowledge_base_document

    content = chm.price_list_markdown().encode("utf-8")
    documents = await db_client.get_documents_for_organization(
        organization_id, limit=200
    )
    existing = next((d for d in documents if d.filename == chm.PRICE_LIST_FILE), None)
    digest = hashlib.sha256(content).hexdigest()
    if (
        existing is not None
        and existing.processing_status == "completed"
        and existing.file_hash == digest
    ):
        LAST_RUN["price_list"] = f"unchanged ({existing.retrieval_mode})"
        return existing.document_uuid, existing.retrieval_mode
    if existing is not None:
        await _delete_document(organization_id, existing)

    async def upload_and_process(mode: str):
        document_uuid = str(uuid.uuid4())
        key = (
            knowledge_base_document_prefix(organization_id, document_uuid)
            + chm.PRICE_LIST_FILE
        )
        if not await storage_fs.acreate_file_from_bytes(key, content):
            raise RuntimeError(f"upload failed: {key}")
        document = await db_client.create_document(
            organization_id=organization_id,
            created_by=owner.id,
            filename=chm.PRICE_LIST_FILE,
            file_size_bytes=0,
            file_hash="",
            mime_type="application/octet-stream",
            custom_metadata={"s3_key": key, "demo_seed": chm.SLUG},
            document_uuid=document_uuid,
            retrieval_mode=mode,
        )
        await process_knowledge_base_document(
            None,
            document_id=document.id,
            s3_key=key,
            organization_id=organization_id,
            created_by_provider_id=str(owner.provider_id),
            retrieval_mode=mode,
        )
        return await db_client.get_document_by_id(document.id)

    document = await upload_and_process("chunked")
    if document is not None and document.processing_status == "completed":
        LAST_RUN["price_list"] = f"chunked, {document.total_chunks} chunks"
        return document.document_uuid, "chunked"
    error = getattr(document, "processing_error", None)
    logger.warning(
        f"Price list: chunked indexing failed ({error}); using full-document mode"
    )
    LAST_RUN["price_list_chunked_error"] = str(error)
    if document is not None:
        await _delete_document(organization_id, document)
    document = await upload_and_process("full_document")
    if document is None or document.processing_status != "completed":
        LAST_RUN["price_list"] = "failed"
        return None, "failed"
    LAST_RUN["price_list"] = "full_document"
    return document.document_uuid, "full_document"


async def _delete_document(organization_id: int, document) -> None:
    key = (document.custom_metadata or {}).get("s3_key")
    if key and key.startswith(f"knowledge_base/{organization_id}/"):
        await storage_fs.adelete_file(key)
    from sqlalchemy import text

    async with db_client.async_session() as session:
        await session.execute(
            text("delete from knowledge_base_chunks where document_id = :d"),
            {"d": document.id},
        )
        await session.execute(
            text("delete from knowledge_base_documents where id = :d"),
            {"d": document.id},
        )
        await session.commit()


async def _sample_orders(organization_id: int, now: datetime) -> str:
    """Store the sample orders (dated from *now*), keeping the lookup key."""
    row = await db_client.get_configuration(
        organization_id, demo_orders.SAMPLE_ORDERS_KEY
    )
    value = row.value if row and isinstance(row.value, dict) else {}
    key = value.get("lookup_key")
    if demo_orders.organization_of_key(key or "") != organization_id:
        key = demo_orders.new_lookup_key(organization_id)
    await db_client.upsert_configuration(
        organization_id,
        demo_orders.SAMPLE_ORDERS_KEY,
        {
            "lookup_key": key,
            "note": chm.ORDERS_NOTE,
            "seeded_at": now.isoformat(),
            "orders": chm.sample_orders(now),
        },
    )
    return key


async def _order_tool(organization_id: int, owner: UserModel, key: str) -> str:
    """The "Look up an order" HTTP tool and its bearer credential."""
    credentials = await db_client.get_credentials_for_organization(organization_id)
    credential = next((c for c in credentials if c.name == chm.CREDENTIAL_NAME), None)
    if credential is None:
        credential = await db_client.create_credential(
            organization_id=organization_id,
            user_id=owner.id,
            name=chm.CREDENTIAL_NAME,
            credential_type="bearer_token",
            credential_data={"token": key},
            description="Demo only: reads the sample orders. Live, this is the shop platform's read-only order API key.",
        )
    elif (credential.credential_data or {}).get("token") != key:
        await db_client.update_credential(
            credential.credential_uuid, organization_id, credential_data={"token": key}
        )
    definition = {
        "schema_version": 1,
        "type": "http_api",
        "config": {
            "method": "POST",
            "url": chm.LOOKUP_URL,
            "credential_uuid": credential.credential_uuid,
            "timeout_ms": 5000,
            "parameters": [
                {
                    "name": "order_number",
                    "type": "string",
                    "description": "The order number the caller gave, e.g. CHM-104203.",
                    "required": True,
                },
                {
                    "name": "email",
                    "type": "string",
                    "description": "The email address used on the order, as confirmed with the caller. Leave empty if they gave a mobile number instead.",
                    "required": False,
                },
                {
                    "name": "phone",
                    "type": "string",
                    "description": "The mobile number used on the order, as the caller said it. Leave empty if they gave an email address instead.",
                    "required": False,
                },
                {
                    "name": "caller_name",
                    "type": "string",
                    "description": "The caller's name, if they gave it.",
                    "required": False,
                },
            ],
            "preset_parameters": [
                {
                    "name": "call_ref",
                    "type": "string",
                    "value_template": "{{initial_context.workflow_run_id}}",
                    "required": True,
                }
            ],
            "customMessage": "One moment while I look that up.",
            "customMessageType": "text",
        },
    }
    description = (
        "Look up a CH Marine order's status. Needs the order number and the "
        "email address or mobile number used on the order. Demo: reads the "
        "20 sample orders; live, it calls the shop's order system."
    )
    tools = await db_client.get_tools_for_organization(organization_id)
    tool = next((t for t in tools if t.name == chm.ORDER_TOOL_NAME), None)
    if tool is None:
        tool = await db_client.create_tool(
            organization_id=organization_id,
            user_id=owner.id,
            name=chm.ORDER_TOOL_NAME,
            definition=definition,
            description=description,
            icon="package",
        )
    else:
        await db_client.update_tool(
            tool.tool_uuid,
            organization_id,
            definition=definition,
            description=description,
        )
    return tool.tool_uuid


async def _update_definitions(workflow_id: int, change) -> None:
    """Apply *change* to the agent, its live version and any draft."""
    async with db_client.async_session() as session:
        workflow = await session.get(WorkflowModel, workflow_id)
        workflow.workflow_definition = change(workflow.workflow_definition or {})
        rows = (
            await session.execute(
                select(WorkflowDefinitionModel).where(
                    WorkflowDefinitionModel.workflow_id == workflow_id,
                    or_(
                        WorkflowDefinitionModel.id == workflow.released_definition_id,
                        WorkflowDefinitionModel.status == "draft",
                    ),
                )
            )
        ).scalars()
        for row in rows:
            row.workflow_json = change(row.workflow_json or {})
        await session.commit()


async def customise_agent(
    organization_id: int, owner: UserModel, workflow: WorkflowModel, now: datetime
) -> WorkflowModel:
    LAST_RUN.clear()
    await db_client.update_business_facts(
        workflow.id, organization_id, {chm.CLOSING_OFFER_KEY: chm.CLOSING_OFFER}
    )
    key = await _sample_orders(organization_id, now)
    tool_uuid = await _order_tool(organization_id, owner, key)
    document_uuid, mode = await _price_list_document(organization_id, owner)
    LAST_RUN["price_list_mode"] = mode
    await _update_definitions(
        workflow.id,
        lambda d: chm.customised_definition(
            d, document_uuid=document_uuid, order_tool_uuid=tool_uuid
        ),
    )
    async with db_client.async_session() as session:
        fresh = await session.get(WorkflowModel, workflow.id)
        assert fresh is not None
        return fresh


async def before_delete(organization_id: int) -> None:
    """Remove the stored price-list files (the rows go with the workspace)."""
    documents = await db_client.get_documents_for_organization(
        organization_id, limit=200
    )
    for document in documents:
        key = (document.custom_metadata or {}).get("s3_key")
        if key and key.startswith(f"knowledge_base/{organization_id}/"):
            await storage_fs.adelete_file(key)

"""A knowledge base request can only use its own document's file (#134 review).

process-document takes the storage key from the request body; the processing
task downloads it and the editor reads and overwrites it. Any other key (another
organization's document, a call transcript, a '..' path) must be refused.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.routes import knowledge_base as routes
from api.schemas.knowledge_base import (
    DocumentUploadRequestSchema,
    ProcessDocumentRequestSchema,
)
from api.services.knowledge_base_keys import (
    is_document_storage_key,
    is_organization_storage_key,
)
from api.tasks import knowledge_base_processing as task

USER = SimpleNamespace(id=1, provider_id="provider-1", selected_organization_id=11)
DOC = "0b7c2f8e-6d1a-4c3b-9a55-1f7e2d3c4b5a"

FOREIGN_KEYS = [
    "transcripts/42.txt",
    "knowledge_base/doc.pdf",
    f"knowledge_base/12/{DOC}/a.pdf",
    "knowledge_base/11/other-document/a.pdf",
    f"knowledge_base/11/{DOC}/../../12/x/a.pdf",
    f"knowledge_base/11/{DOC}/sub/a.pdf",
    f"knowledge_base/11/{DOC}/..",
    f"knowledge_base/11/{DOC}/a\\..\\b.pdf",
    f"knowledge_base/11/{DOC}/",
    f"knowledge_base/111/{DOC}/a.pdf",
]


def test_only_the_documents_own_file_is_accepted():
    assert is_document_storage_key(f"knowledge_base/11/{DOC}/a.pdf", 11, DOC)
    for key in FOREIGN_KEYS:
        assert not is_document_storage_key(key, 11, DOC), key
    # A document uuid can't smuggle in a path either.
    assert not is_document_storage_key("knowledge_base/11/../x/a.pdf", 11, "../x")


def test_organization_keys():
    assert is_organization_storage_key(f"knowledge_base/11/{DOC}/a.pdf", 11)
    assert not is_organization_storage_key("transcripts/42.txt", 11)
    assert not is_organization_storage_key(f"knowledge_base/12/{DOC}/a.pdf", 11)
    assert not is_organization_storage_key("knowledge_base/11/../12/x/a.pdf", 11)
    assert not is_organization_storage_key(f"knowledge_base/11/{DOC}/x/a.pdf", 11)


@pytest.fixture
def no_side_effects(monkeypatch):
    create = AsyncMock()
    enqueue = AsyncMock()
    monkeypatch.setattr(routes.db_client, "create_document", create)
    monkeypatch.setattr(routes, "enqueue_document_processing", enqueue)
    return create, enqueue


@pytest.mark.asyncio
@pytest.mark.parametrize("key", FOREIGN_KEYS)
async def test_process_document_refuses_foreign_keys(no_side_effects, key):
    create, enqueue = no_side_effects

    with pytest.raises(HTTPException) as error:
        await routes.process_document(
            request=ProcessDocumentRequestSchema(
                document_uuid=DOC, s3_key=key, retrieval_mode="full_document"
            ),
            user=USER,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "The file key does not belong to this document"
    create.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../a.pdf", "a/b.pdf", "a\\b.pdf", "..", ""])
async def test_upload_url_refuses_paths_in_the_file_name(monkeypatch, filename):
    presign = AsyncMock()
    monkeypatch.setattr(routes.storage_fs, "aget_presigned_put_url", presign)

    with pytest.raises(HTTPException) as error:
        await routes.get_upload_url(
            request=DocumentUploadRequestSchema(
                filename=filename, mime_type="application/pdf"
            ),
            user=USER,
        )

    assert error.value.status_code == 400
    presign.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_never_downloads_another_organizations_file(monkeypatch):
    update_status = AsyncMock()
    download = AsyncMock()
    monkeypatch.setattr(task.db_client, "update_document_status", update_status)
    monkeypatch.setattr(task.storage_fs, "adownload_file", download)

    await task.process_knowledge_base_document(
        {}, 5, "transcripts/42.txt", 11, "provider-1", retrieval_mode="full_document"
    )

    download.assert_not_awaited()
    update_status.assert_awaited_once_with(
        5, "failed", error_message="The document's file is missing."
    )

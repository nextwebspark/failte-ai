"""The processing task parses, chunks, embeds and stores documents locally (#126).

Storage and the embeddings provider are faked; the database is the test DB.
"""

import hashlib
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.configuration.registry import (
    GoogleVertexEmbeddingsConfiguration,
    OpenAIEmbeddingsConfiguration,
)
from api.services.gen_ai import EmbeddingSettings
from api.tasks import knowledge_base_processing as task
from api.tests.support.documents import make_docx, make_pdf


class FakeEmbedder:
    def __init__(self):
        self.texts: list[str] = []

    def get_model_id(self):
        return "fake-embedding"

    def get_embedding_dimension(self):
        return 1536

    async def embed_texts(self, texts):
        self.texts.extend(texts)
        return [[float(i + 1)] + [0.0] * 1535 for i in range(len(texts))]


@pytest.fixture
def stored_file(monkeypatch, tmp_path):
    """Serve one local file as the object in storage."""
    source = {}

    async def download(_key, local_path):
        shutil.copyfile(source["path"], local_path)
        return True

    monkeypatch.setattr(task.storage_fs, "adownload_file", download)

    def put(name: str, data: bytes) -> str:
        path = tmp_path / name
        path.write_bytes(data)
        source["path"] = str(path)
        return str(path)

    return put


@pytest.fixture
def embeddings(monkeypatch):
    """Configure the org's embeddings and capture the service the task builds."""
    from api.services.configuration import ai_model_configuration

    state = SimpleNamespace(config=None, embedder=FakeEmbedder(), settings=[])

    state.platform_managed = False

    async def resolved(**_kwargs):
        return SimpleNamespace(
            effective=SimpleNamespace(
                embeddings=state.config, platform_managed=state.platform_managed
            )
        )

    async def build(*, db_client, settings, **_kwargs):
        state.settings.append(settings)
        return state.embedder

    monkeypatch.setattr(
        ai_model_configuration, "get_resolved_ai_model_configuration", resolved
    )
    monkeypatch.setattr(task, "build_embedding_service", build)
    return state


async def _document(db_session, slug: str, filename: str, mode: str):
    user, _ = await db_session.get_or_create_user_by_provider_id(f"{slug}_user")
    org, _ = await db_session.get_or_create_organization_by_provider_id(
        f"{slug}_org", user.id
    )
    s3_key = f"knowledge_base/{org.id}/{slug}/{filename}"
    document = await db_session.create_document(
        organization_id=org.id,
        created_by=user.id,
        filename=filename,
        file_size_bytes=0,
        file_hash="",
        mime_type="application/octet-stream",
        custom_metadata={"s3_key": s3_key},
        retrieval_mode=mode,
    )
    return document, s3_key, org.id


async def _run(document, s3_key, org_id, mode):
    await task.process_knowledge_base_document(
        {}, document.id, s3_key, org_id, "provider-1", retrieval_mode=mode
    )


async def test_docx_is_chunked_embedded_and_stored(
    db_session, tmp_path, stored_file, embeddings
):
    docx_path = tmp_path / "source.docx"
    make_docx(str(docx_path))
    stored_file("handbook.docx", docx_path.read_bytes())
    embeddings.config = OpenAIEmbeddingsConfiguration(api_key="sk-test")
    document, s3_key, org_id = await _document(
        db_session, "kb_local_docx", "handbook.docx", "chunked"
    )

    await _run(document, s3_key, org_id, "chunked")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "completed", stored.processing_error
    assert stored.total_chunks == 3
    assert stored.mime_type.endswith("wordprocessingml.document")
    assert stored.docling_metadata["parser"] == "lightmove"
    assert stored.docling_metadata["title"] == "Staff Handbook"
    # The contextualized text is what gets embedded.
    assert embeddings.embedder.texts[0] == (
        "Staff Handbook > Opening hours\n\nWe are open Monday to Friday, 9am to 5pm."
    )
    assert embeddings.settings[0].api_key == "sk-test"

    results = await db_session.search_similar_chunks(
        query_embedding=[1.0] + [0.0] * 1535,
        organization_id=org_id,
        limit=5,
        embedding_model="fake-embedding",
    )
    assert sorted(r["chunk_index"] for r in results) == [0, 1, 2]
    first = next(r for r in results if r["chunk_index"] == 0)
    assert first["chunk_text"] == "We are open Monday to Friday, 9am to 5pm."
    assert first["chunk_metadata"] == {"headings": ["Opening hours"]}


async def test_pdf_full_document_needs_no_embeddings(
    db_session, stored_file, embeddings
):
    data = make_pdf([["Returns within 30 days."], ["Shipping takes 2 days."]])
    stored_file("policy.pdf", data)
    document, s3_key, org_id = await _document(
        db_session, "kb_local_pdf_full", "policy.pdf", "full_document"
    )

    await _run(document, s3_key, org_id, "full_document")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "completed", stored.processing_error
    assert stored.full_text == "Returns within 30 days.\n\nShipping takes 2 days."
    assert stored.file_hash == hashlib.sha256(data).hexdigest()
    assert stored.docling_metadata["pages"] == 2
    assert embeddings.settings == []


async def test_scanned_pdf_fails_with_a_clear_message(
    db_session, stored_file, embeddings
):
    stored_file("scan.pdf", make_pdf([[]]))
    document, s3_key, org_id = await _document(
        db_session, "kb_local_scan", "scan.pdf", "full_document"
    )

    await _run(document, s3_key, org_id, "full_document")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "failed"
    assert stored.processing_error == (
        "No text found in this PDF. Scanned documents aren't supported yet."
    )


async def test_chunked_without_embeddings_fails_clearly(
    db_session, stored_file, embeddings
):
    stored_file("notes.md", b"# Notes\n\nSome text.")
    document, s3_key, org_id = await _document(
        db_session, "kb_local_noemb", "notes.md", "chunked"
    )

    await _run(document, s3_key, org_id, "chunked")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "failed"
    assert stored.processing_error == task.EMBEDDINGS_NOT_CONFIGURED_MESSAGE
    assert embeddings.embedder.texts == []


async def test_vertex_embeddings_need_no_api_key(db_session, stored_file, embeddings):
    stored_file("faq.html", b"<h1>FAQ</h1><p>We open at nine.</p>")
    embeddings.config = GoogleVertexEmbeddingsConfiguration(project_id="eu-project")
    document, s3_key, org_id = await _document(
        db_session, "kb_local_vertex", "faq.html", "chunked"
    )

    await _run(document, s3_key, org_id, "chunked")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "completed", stored.processing_error
    (settings,) = embeddings.settings
    assert isinstance(settings, EmbeddingSettings)
    assert (settings.provider, settings.project_id, settings.location) == (
        "google_vertex",
        "eu-project",
        "europe-west1",
    )
    assert embeddings.embedder.texts == ["FAQ\n\nWe open at nine."]


async def test_oversized_files_are_still_refused(
    db_session, monkeypatch, stored_file, embeddings
):
    stored_file("big.txt", b"a " * (task.MAX_FILE_SIZE_BYTES // 2 + 1))
    document, s3_key, org_id = await _document(
        db_session, "kb_local_big", "big.txt", "full_document"
    )
    parse = AsyncMock()
    monkeypatch.setattr(task, "process_document", parse)

    await _run(document, s3_key, org_id, "full_document")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "failed"
    assert "exceeds the maximum allowed size of 5MB" in stored.processing_error
    parse.assert_not_awaited()


async def test_documents_embedded_with_another_model_need_reindex(
    db_session, tmp_path, stored_file, embeddings, test_client_factory
):
    stored_file("faq.md", b"# FAQ\n\nWe open at nine.")
    # Indexed with the fake embedder ("fake-embedding")...
    embeddings.config = OpenAIEmbeddingsConfiguration(
        api_key="sk-test", model="fake-embedding"
    )
    document, s3_key, org_id = await _document(
        db_session, "kb_local_reindex", "faq.md", "chunked"
    )
    await _run(document, s3_key, org_id, "chunked")
    user = await db_session.get_user_by_id(document.created_by)
    await db_session.update_user_selected_organization(user.id, org_id)
    user = await db_session.get_user_by_id(user.id)

    async def listed():
        async with test_client_factory(user) as client:
            response = await client.get("/api/v1/knowledge-base/documents")
            single = await client.get(
                f"/api/v1/knowledge-base/documents/{document.document_uuid}"
            )
        assert response.status_code == 200, response.text
        (row,) = response.json()["documents"]
        assert single.json()["needs_reindex"] == row["needs_reindex"]
        return row["needs_reindex"]

    assert await listed() is False

    # ...then the organization switches to another embedding model.
    embeddings.config = GoogleVertexEmbeddingsConfiguration(project_id="eu-project")
    assert await listed() is True

    # No embedding model at all: nothing to compare against, no hint.
    embeddings.config = None
    assert await listed() is False


async def test_platform_orgs_without_embeddings_get_a_platform_message(
    db_session, stored_file, embeddings
):
    stored_file("notes.md", b"# Notes\n\nSome text.")
    embeddings.platform_managed = True  # server lost its platform settings
    document, s3_key, org_id = await _document(
        db_session, "kb_local_platform_noemb", "notes.md", "chunked"
    )

    await _run(document, s3_key, org_id, "chunked")

    stored = await db_session.get_document_by_id(document.id)
    assert stored.processing_status == "failed"
    assert stored.processing_error == task.PLATFORM_EMBEDDINGS_UNAVAILABLE_MESSAGE
    assert "Model Configurations" not in stored.processing_error

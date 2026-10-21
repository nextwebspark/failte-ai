"""ARQ background task for processing knowledge base documents.

Downloads the file from storage, parses and chunks it on this server
(api.services.documents), embeds the chunks with the organization's embeddings
provider and stores the result. The document itself is never sent to another
service; in chunked mode only its chunk text goes to the embeddings provider.
"""

import os
import tempfile

from loguru import logger

from api.db import db_client
from api.db.models import KnowledgeBaseChunkModel
from api.services.documents import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    DocumentParseError,
    process_document,
)
from api.services.gen_ai import EmbeddingSettings, build_embedding_service
from api.services.knowledge_base_keys import is_organization_storage_key
from api.services.storage import storage_fs

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
EMBEDDINGS_NOT_CONFIGURED_MESSAGE = (
    "No embedding model is configured. Set one in Model Configurations > "
    "Embedding to use chunked search."
)
# Platform organizations can't configure embeddings themselves; theirs come
# from the server's platform settings.
PLATFORM_EMBEDDINGS_UNAVAILABLE_MESSAGE = (
    "Chunked search isn't available on this server right now. Upload the "
    "document in full-document mode, or contact LightMove.ai support."
)


def document_processing_available() -> bool:
    """Whether uploaded documents can be converted and chunked on this server.

    Always true: documents are parsed and chunked in-process. Kept as the one
    place to turn uploads off should processing ever depend on configuration.
    """
    return True


EMBEDDING_BATCH_SIZE = 64


async def _embed_texts_in_batches(
    embedding_service,
    texts: list[str],
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> list[list[float]]:
    """Generate embeddings in bounded batches for provider stability."""
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        logger.info(
            f"Generating embedding batch {start // batch_size + 1} ({len(batch)} texts)"
        )
        embeddings.extend(await embedding_service.embed_texts(batch))
    return embeddings


async def process_knowledge_base_document(
    ctx,
    document_id: int,
    s3_key: str,
    organization_id: int,
    created_by_provider_id: str,
    max_tokens: int = DEFAULT_TARGET_TOKENS,
    retrieval_mode: str = "chunked",
):
    """Process a knowledge base document: download, parse, chunk, embed, store.

    Args:
        ctx: ARQ context
        document_id: Database ID of the document
        s3_key: S3 key where the file is stored
        organization_id: Organization ID
        created_by_provider_id: Uploading user's provider ID
        max_tokens: Target tokens per chunk (estimated, default 400)
        retrieval_mode: "chunked" for vector search or "full_document" for full text
    """
    logger.info(
        f"Processing knowledge base document: document_id={document_id}, "
        f"s3_key={s3_key}, org={organization_id}, mode={retrieval_mode}"
    )

    temp_file_path = None

    if not is_organization_storage_key(s3_key, organization_id):
        # Defence in depth: the route only queues keys in the document's own
        # folder; never download anything else.
        logger.error(
            f"Document {document_id}: refusing storage key outside organization "
            f"{organization_id}'s knowledge base"
        )
        await db_client.update_document_status(
            document_id, "failed", error_message="The document's file is missing."
        )
        return

    try:
        await db_client.update_document_status(document_id, "processing")

        filename = s3_key.split("/")[-1]
        file_extension = os.path.splitext(filename)[1] or ".bin"

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_extension)
        temp_file_path = temp_file.name
        temp_file.close()

        logger.info(f"Downloading file from S3: {s3_key}")
        download_success = await storage_fs.adownload_file(s3_key, temp_file_path)
        if not download_success:
            raise Exception(f"Failed to download file from S3: {s3_key}")
        if not os.path.exists(temp_file_path):
            raise FileNotFoundError(f"Downloaded file not found: {temp_file_path}")

        file_size = os.path.getsize(temp_file_path)
        logger.info(f"Downloaded file size: {file_size} bytes")

        if file_size > MAX_FILE_SIZE_BYTES:
            error_message = (
                f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds the "
                f"maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB."
            )
            logger.warning(f"Document {document_id}: {error_message}")
            await db_client.update_document_status(
                document_id, "failed", error_message=error_message
            )
            return

        file_hash = db_client.compute_file_hash(temp_file_path)
        mime_type = db_client.get_mime_type(temp_file_path)

        document = await db_client.get_document_by_id(document_id)
        if not document:
            raise Exception(f"Document {document_id} not found")

        # Reject duplicates (same hash already ingested for this org).
        existing_doc = await db_client.get_document_by_hash(file_hash, organization_id)
        if existing_doc and existing_doc.id != document_id:
            error_message = (
                f"This content is identical to '{existing_doc.filename}'. "
                f"Keep only one copy of it in the knowledge base."
            )
            logger.warning(
                f"Duplicate document detected: {document_id} is duplicate of "
                f"{existing_doc.id} ({existing_doc.filename})"
            )
            await db_client.update_document_metadata(
                document_id,
                file_size_bytes=file_size,
                file_hash=file_hash,
                mime_type=mime_type,
            )
            await db_client.update_document_status(
                document_id,
                "failed",
                error_message=error_message,
                docling_metadata={
                    "duplicate_of": existing_doc.document_uuid,
                    "duplicate_filename": existing_doc.filename,
                },
            )
            return

        await db_client.update_document_metadata(
            document_id,
            file_size_bytes=file_size,
            file_hash=file_hash,
            mime_type=mime_type,
        )

        embedding_settings = None
        platform_managed = False
        if retrieval_mode == "chunked":
            from api.services.configuration.ai_model_configuration import (
                get_resolved_ai_model_configuration,
            )

            resolved_config = await get_resolved_ai_model_configuration(
                organization_id=document.organization_id,
            )
            platform_managed = bool(
                getattr(resolved_config.effective, "platform_managed", False)
            )
            embedding_settings = EmbeddingSettings.from_config(
                resolved_config.effective.embeddings
            )
            if embedding_settings is not None:
                logger.info(
                    f"Using embeddings config: provider={embedding_settings.provider}, "
                    f"model={embedding_settings.model}"
                )

        logger.info(f"Parsing document on this server (mode={retrieval_mode})")
        try:
            result = await process_document(
                temp_file_path,
                filename,
                mime_type,
                retrieval_mode,
                max_tokens=max_tokens,
                overlap_tokens=min(DEFAULT_OVERLAP_TOKENS, max_tokens // 4),
            )
        except DocumentParseError as exc:
            logger.warning(f"Document {document_id}: {exc}")
            await db_client.update_document_status(
                document_id, "failed", error_message=str(exc)
            )
            return

        docling_metadata = result.get("docling_metadata", {})

        if retrieval_mode == "full_document":
            full_text = result.get("full_text") or ""
            await db_client.update_document_full_text(document_id, full_text)
            await db_client.update_document_status(
                document_id,
                "completed",
                total_chunks=0,
                docling_metadata=docling_metadata,
            )
            logger.info(
                f"Successfully processed full_document {document_id}. "
                f"Text length: {len(full_text)} chars"
            )
            return

        if embedding_settings is None or not embedding_settings.is_configured:
            message = (
                PLATFORM_EMBEDDINGS_UNAVAILABLE_MESSAGE
                if platform_managed
                else EMBEDDINGS_NOT_CONFIGURED_MESSAGE
            )
            logger.warning(f"Document {document_id}: {message}")
            await db_client.update_document_status(
                document_id, "failed", error_message=message
            )
            return

        # Ingestion runs outside any workflow run, so resolve the MPS correlation
        # id here (LightMove.ai-managed embeddings only).
        embedding_service = await build_embedding_service(
            db_client=db_client,
            settings=embedding_settings,
            resolve_correlation=True,
        )

        chunks = result.get("chunks", [])

        chunk_records = []
        chunk_texts = []
        for chunk in chunks:
            contextualized = chunk.get("contextualized_text") or chunk["chunk_text"]
            chunk_records.append(
                KnowledgeBaseChunkModel(
                    document_id=document_id,
                    organization_id=organization_id,
                    chunk_text=chunk["chunk_text"],
                    contextualized_text=contextualized,
                    chunk_index=chunk["chunk_index"],
                    chunk_metadata=chunk.get("chunk_metadata") or {},
                    embedding_model=embedding_service.get_model_id(),
                    embedding_dimension=embedding_service.get_embedding_dimension(),
                    token_count=chunk.get("token_count", 0),
                )
            )
            chunk_texts.append(contextualized)

        logger.info(
            f"Generating embeddings for {len(chunk_texts)} chunks "
            f"using {embedding_service.get_model_id()}"
        )
        embeddings = await _embed_texts_in_batches(embedding_service, chunk_texts)
        if len(embeddings) != len(chunk_records):
            raise ValueError(
                "Embedding count mismatch: "
                f"expected {len(chunk_records)}, got {len(embeddings)}"
            )
        for chunk_record, embedding in zip(chunk_records, embeddings):
            chunk_record.embedding = embedding

        logger.info("Storing chunks in database")
        await db_client.replace_chunks_for_document(
            document_id=document_id,
            organization_id=organization_id,
            chunks=chunk_records,
        )

        await db_client.update_document_status(
            document_id,
            "completed",
            total_chunks=len(chunk_records),
            docling_metadata=docling_metadata,
        )

        logger.info(
            f"Successfully processed knowledge base document {document_id}. "
            f"Total chunks: {len(chunk_records)}"
        )

    except Exception as e:
        logger.exception(
            "Error processing knowledge base document {}: {}", document_id, e
        )
        await db_client.update_document_status(
            document_id, "failed", error_message=str(e)
        )
        raise

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.debug(f"Cleaned up temp file: {temp_file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_file_path}: {e}")

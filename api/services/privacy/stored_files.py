"""Deleting uploaded files for good: knowledge base documents and prompt audio.

Both used to be soft deletes that kept the row and the stored object. Now the
stored object goes first and the row only once it is gone, so a storage outage
leaves everything in place for a retry instead of an orphaned file nobody can
find any more.

Only keys inside the organization's own prefix are deleted. The keys are
recorded from what the client sent at upload time, so a key outside that
prefix is never trusted to name this organization's object.
"""

import re
from typing import Optional

from loguru import logger

from api.db import db_client
from api.services.retention.purge import (
    StorageResolver,
    current_storage_backend,
    default_storage_resolver,
)


class StoredFileDeleteError(Exception):
    """The stored object could not be deleted; nothing was changed."""


def knowledge_base_document_prefix(organization_id: int, document_uuid: str) -> str:
    return f"knowledge_base/{organization_id}/{document_uuid}/"


def is_safe_storage_key(key: object) -> bool:
    """A plain relative object key: no ``..`` segment, backslash or empty segment.

    Object stores treat keys as opaque strings, but a key that only looks
    inside a folder (``knowledge_base/1/u/../../2/x``) must not pass a prefix
    check, and local or proxied storage may resolve it as a path.
    """
    if not isinstance(key, str) or not key or key.startswith("/"):
        return False
    if "\\" in key or any(ord(char) < 32 for char in key):
        return False
    return all(segment not in ("", ".", "..") for segment in key.split("/"))


def is_knowledge_base_document_key(
    organization_id: int, document_uuid: str, key: object
) -> bool:
    """Whether ``key`` is a file of this document, in its organization's folder."""
    return is_safe_storage_key(key) and key.startswith(
        knowledge_base_document_prefix(organization_id, document_uuid)
    )


def is_workflow_recording_key(organization_id: int, key: str) -> bool:
    """Whether ``key`` is prompt audio of this organization.

    Prompt audio lives at ``recordings/{org_id}/{recording_id}/{file}``. The
    same ``recordings/`` prefix holds call recordings
    (``recordings/{run_id}/user.wav``, ``recordings/{run_id}/noveum/...``), so
    an organization id that equals a run id must not reach that run's audio.
    """
    if not is_safe_storage_key(key):
        return False
    match = re.fullmatch(rf"recordings/{organization_id}/([^/]+)/.+", key)
    return bool(match) and match.group(1) != "noveum"


async def delete_knowledge_base_document(
    *,
    organization_id: int,
    document_uuid: str,
    resolve_storage: Optional[StorageResolver] = None,
    archived_only: bool = False,
) -> bool:
    """Delete a document's stored file, then its row and chunks.

    Returns False when the organization has no such document (no archived
    one, with ``archived_only``). Raises ``StoredFileDeleteError`` (and keeps
    the row) when the file cannot be deleted.
    """
    is_active = False if archived_only else None
    document = await db_client.get_document_for_deletion(
        document_uuid, organization_id, is_active=is_active
    )
    if document is None:
        return False

    resolve_storage = resolve_storage or default_storage_resolver()
    prefix = knowledge_base_document_prefix(organization_id, document.document_uuid)
    key = (document.custom_metadata or {}).get("s3_key")
    try:
        storage = resolve_storage(current_storage_backend())
        if is_knowledge_base_document_key(organization_id, document.document_uuid, key):
            if not await storage.adelete_file(key):
                raise StoredFileDeleteError(f"Could not delete {key}")
        elif key:
            logger.warning(
                f"Knowledge base document {document.document_uuid} names a file "
                "outside its organization's folder; leaving that file alone"
            )
        if (
            is_safe_storage_key(prefix.rstrip("/"))
            and "/" not in document.document_uuid
        ):
            await storage.adelete_prefix(prefix)
    except StoredFileDeleteError:
        raise
    except Exception as exc:
        raise StoredFileDeleteError(type(exc).__name__) from exc

    return await db_client.delete_document(
        document_uuid, organization_id, is_active=is_active
    )


async def delete_workflow_recording(
    *,
    organization_id: int,
    recording_id: str,
    resolve_storage: Optional[StorageResolver] = None,
) -> bool:
    """Delete an active prompt recording's audio, then its row.

    Returns False when the organization has no such active recording. Raises
    ``StoredFileDeleteError`` (and keeps the row) when the audio cannot be
    deleted.
    """
    recording = await db_client.get_recording_for_deletion(
        organization_id, recording_id=recording_id, is_active=True
    )
    return await _delete_recording(organization_id, recording, True, resolve_storage)


async def delete_archived_workflow_recording(
    *,
    organization_id: int,
    recording_pk: int,
    resolve_storage: Optional[StorageResolver] = None,
) -> bool:
    """Delete an archived (soft-deleted) recording's audio, then its row."""
    recording = await db_client.get_recording_for_deletion(
        organization_id, recording_pk=recording_pk, is_active=False
    )
    return await _delete_recording(organization_id, recording, False, resolve_storage)


async def _delete_recording(
    organization_id: int,
    recording,
    is_active: bool,
    resolve_storage: Optional[StorageResolver],
) -> bool:
    if recording is None:
        return False

    resolve_storage = resolve_storage or default_storage_resolver()
    key = recording.storage_key
    if key and is_workflow_recording_key(organization_id, key):
        try:
            deleted = await resolve_storage(recording.storage_backend).adelete_file(key)
        except Exception as exc:
            raise StoredFileDeleteError(type(exc).__name__) from exc
        if not deleted:
            raise StoredFileDeleteError(f"Could not delete {key}")
    elif key:
        logger.warning(
            f"Recording {recording.id} of organization {organization_id} names a "
            "file outside its organization's folder; leaving that file alone"
        )

    return await db_client.delete_recording(
        organization_id, recording.id, is_active=is_active
    )

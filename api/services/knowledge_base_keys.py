"""Storage keys of knowledge base files, and which ones a request may use.

/upload-url puts every file at ``knowledge_base/{org_id}/{document_uuid}/{name}``.
Processing reads that key and the editor overwrites it, so any key taken from a
request or a stored row is checked against this layout first.
"""


def knowledge_base_document_prefix(organization_id: int, document_uuid: str) -> str:
    """Where /upload-url puts a document's file: one folder per document."""
    return f"knowledge_base/{organization_id}/{document_uuid}/"


def is_safe_document_filename(filename: str) -> bool:
    """A plain file name: no folders, no backslashes, not '.' or '..'."""
    return (
        bool(filename)
        and filename not in (".", "..")
        and not any(separator in filename for separator in ("/", "\\", "\x00"))
    )


def is_document_storage_key(key: str, organization_id: int, document_uuid: str) -> bool:
    """Whether *key* is the file /upload-url minted for this document.

    Anything else (another organization's file, a call transcript, a path
    with '..' segments) must never be read, processed or overwritten.
    """
    if not is_safe_document_filename(document_uuid):
        return False
    prefix = knowledge_base_document_prefix(organization_id, document_uuid)
    return key.startswith(prefix) and is_safe_document_filename(key[len(prefix) :])


def is_organization_storage_key(key: str, organization_id: int) -> bool:
    """Whether *key* lies in one of this organization's document folders."""
    prefix = f"knowledge_base/{organization_id}/"
    if not key.startswith(prefix) or "\\" in key:
        return False
    parts = key[len(prefix) :].split("/")
    return len(parts) == 2 and all(part and part not in (".", "..") for part in parts)

"""Vault orchestration (SPEC.md section 7.1): ties the DB (per-case data
key), KeyManager (wrap/unwrap), and BlobStore (ciphertext storage)
together. This is the only place document plaintext exists outside the
API layer that receives an upload — downstream code reads it back through
`read_document`, never the BlobStore directly, so every access is
audited (CLAUDE.md invariant 4: an audit_log row per access, never
document text or PII in the row itself).

Every seal/open call carries associated data binding the ciphertext to
the context it belongs to (M4.1 hardening): a case's wrapped data key is
bound to that case's id, and a document's ciphertext is bound to its
case id, document id, and content hash. A blob or wrapped key that ends
up decrypted in the wrong context (swapped on disk, copied to another
case, a stale pointer) fails closed with InvalidTag instead of silently
returning plaintext that doesn't belong there.

Blob storage keys are the document id, not the content hash: two
different cases uploading byte-identical content (e.g. the same benign
fixture used across packets) would otherwise collide on the same
LocalBlobStore path and overwrite each other, since the store has no
notion of "case" on its own. `Document.sha256` still records the content
hash for duplicate-detection within a case (app/api/cases.py); it's just
no longer doubling as the storage address.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy.orm import Session

from app.core.orm import AuditLog, Case, Document
from app.vault import aead
from app.vault.blob_store import BlobStore
from app.vault.key_manager import KeyManager

# Which KeyManager/scheme wrapped a case's data key — see
# Document.key_id's docstring in app/core/orm.py.
KEY_SCHEME_ID = "local-v1"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case_aad(case_id: uuid.UUID) -> bytes:
    return str(case_id).encode()


def _document_aad(case_id: uuid.UUID, document_id: uuid.UUID, sha256: str) -> bytes:
    return f"{case_id}|{document_id}|{sha256}".encode()


def create_wrapped_case_key(key_manager: KeyManager, *, case_id: uuid.UUID) -> bytes:
    """A fresh per-case data key, wrapped and ready to store on a new
    Case.wrapped_data_key (app/api/cases.py, at case creation). `case_id`
    must be the id that new Case row will actually get — generate it
    client-side before constructing the Case, rather than relying on the
    ORM's flush-time default, so it's known here."""
    return key_manager.wrap_key(aead.generate_key(), aad=_case_aad(case_id))


def _case_data_key(case: Case, key_manager: KeyManager) -> bytes:
    return key_manager.unwrap_key(case.wrapped_data_key, aad=_case_aad(case.id))


def store_document(
    session: Session,
    *,
    case: Case,
    key_manager: KeyManager,
    blob_store: BlobStore,
    slot: str,
    content: bytes,
    actor: str,
) -> Document:
    data_key = _case_data_key(case, key_manager)
    digest = sha256_hex(content)
    document_id = uuid.uuid4()
    aad = _document_aad(case.id, document_id, digest)
    blob_store.put(str(document_id), aead.seal(data_key, content, aad))

    document = Document(
        id=document_id,
        case_id=case.id,
        slot=slot,
        sha256=digest,
        key_id=KEY_SCHEME_ID,
        storage_ref=str(document_id),
    )
    session.add(document)
    session.flush()  # also assigns created_at before the audit row's "object exists" window

    session.add(
        AuditLog(
            actor=actor,
            action="document_uploaded",
            case_id=case.id,
            object_ref=str(document.id),
            detail={"slot": slot, "sha256": digest, "size_bytes": len(content)},
        )
    )
    return document


def read_document(
    session: Session,
    *,
    case: Case,
    document: Document,
    key_manager: KeyManager,
    blob_store: BlobStore,
    actor: str,
) -> bytes:
    data_key = _case_data_key(case, key_manager)
    aad = _document_aad(case.id, document.id, document.sha256)
    plaintext = aead.open_(data_key, blob_store.get(document.storage_ref), aad)

    session.add(
        AuditLog(
            actor=actor,
            action="document_read",
            case_id=case.id,
            object_ref=str(document.id),
            detail={"slot": document.slot, "sha256": document.sha256},
        )
    )
    return plaintext

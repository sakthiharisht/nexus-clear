"""Vault orchestration (SPEC.md section 7.1): ties the DB (per-case data
key), KeyManager (wrap/unwrap), and BlobStore (ciphertext storage)
together. This is the only place document plaintext exists outside the
API layer that receives an upload — downstream code reads it back through
`read_document`, never the BlobStore directly, so every access is
audited (CLAUDE.md invariant 4: an audit_log row per access, never
document text or PII in the row itself).
"""

from __future__ import annotations

import hashlib

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


def create_wrapped_case_key(key_manager: KeyManager) -> bytes:
    """A fresh per-case data key, wrapped and ready to store on a new
    Case.wrapped_data_key (app/api/cases.py, at case creation)."""
    return key_manager.wrap_key(aead.generate_key())


def _case_data_key(case: Case, key_manager: KeyManager) -> bytes:
    return key_manager.unwrap_key(case.wrapped_data_key)


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
    blob_store.put(digest, aead.seal(data_key, content))

    document = Document(
        case_id=case.id, slot=slot, sha256=digest, key_id=KEY_SCHEME_ID, storage_ref=digest
    )
    session.add(document)
    session.flush()  # assigns document.id before the audit row references it

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
    plaintext = aead.open_(data_key, blob_store.get(document.storage_ref))

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

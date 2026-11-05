"""Integration tests for app/vault/service.py: real Postgres session
(tests/conftest.py's db_session), real envelope encryption, real local
blob store. CLAUDE.md: no document text or PII in audit_log.detail -
asserted directly against what actually got written, not just inferred.
"""

import hashlib
import secrets
import uuid
from datetime import date
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy.orm import Session

from app.core.orm import AuditLog, Case
from app.vault import service
from app.vault.blob_store import LocalBlobStore
from app.vault.key_manager import LocalKeyManager

SYNTHETIC_PII = "SSN 123-45-6789"  # must never appear in any logged/audited text


def _make_case(db_session: Session, key_manager: LocalKeyManager) -> Case:
    case_id = uuid.uuid4()
    case = Case(
        id=case_id,
        provider_profile={"legal_name": "Christopher Lee"},
        payer="BCBSTX",
        provider_type="LPC",
        target_date=date(2026, 11, 17),
        wrapped_data_key=service.create_wrapped_case_key(key_manager, case_id=case_id),
        provider_token=secrets.token_urlsafe(24),
    )
    db_session.add(case)
    db_session.flush()
    return case


def test_upload_then_read_round_trips_the_original_bytes(
    db_session: Session, tmp_path: Path
) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case = _make_case(db_session, key_manager)

    content = f"synthetic license PDF bytes. {SYNTHETIC_PII}".encode()
    document = service.store_document(
        db_session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=content,
        actor="provider",
    )

    read_back = service.read_document(
        db_session,
        case=case,
        document=document,
        key_manager=key_manager,
        blob_store=blob_store,
        actor="provider",
    )
    assert read_back == content


def test_stored_blob_is_not_the_plaintext(db_session: Session, tmp_path: Path) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case = _make_case(db_session, key_manager)

    content = f"synthetic document. {SYNTHETIC_PII}".encode()
    document = service.store_document(
        db_session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=content,
        actor="provider",
    )

    on_disk = blob_store.get(document.storage_ref)
    assert content not in on_disk
    assert SYNTHETIC_PII.encode() not in on_disk


def test_upload_writes_an_audit_row_with_no_document_text_or_pii(
    db_session: Session, tmp_path: Path
) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case = _make_case(db_session, key_manager)

    content = f"synthetic COI PDF bytes. {SYNTHETIC_PII}".encode()
    document = service.store_document(
        db_session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="coi",
        content=content,
        actor="provider",
    )
    db_session.flush()

    rows = (
        db_session.query(AuditLog)
        .filter_by(case_id=case.id, action="document_uploaded")
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.object_ref == str(document.id)
    serialized_detail = str(row.detail)
    assert SYNTHETIC_PII not in serialized_detail
    assert "synthetic COI PDF bytes" not in serialized_detail
    assert row.detail == {"slot": "coi", "sha256": document.sha256, "size_bytes": len(content)}


def test_read_writes_a_separate_audit_row(db_session: Session, tmp_path: Path) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case = _make_case(db_session, key_manager)

    document = service.store_document(
        db_session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=b"synthetic bytes",
        actor="provider",
    )
    service.read_document(
        db_session,
        case=case,
        document=document,
        key_manager=key_manager,
        blob_store=blob_store,
        actor="reviewer",
    )
    db_session.flush()

    read_rows = (
        db_session.query(AuditLog)
        .filter_by(case_id=case.id, action="document_read")
        .all()
    )
    assert len(read_rows) == 1
    assert read_rows[0].actor == "reviewer"


def test_different_cases_get_different_data_keys(db_session: Session, tmp_path: Path) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    case_a = _make_case(db_session, key_manager)
    case_b = _make_case(db_session, key_manager)
    assert case_a.wrapped_data_key != case_b.wrapped_data_key


def test_document_from_one_case_cannot_be_decrypted_with_another_cases_key(
    db_session: Session, tmp_path: Path
) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case_a = _make_case(db_session, key_manager)
    case_b = _make_case(db_session, key_manager)

    document = service.store_document(
        db_session,
        case=case_a,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=b"case A's document",
        actor="provider",
    )

    with pytest.raises(InvalidTag):
        service.read_document(
            db_session,
            case=case_b,  # wrong case -> wrong (unwrapped) data key
            document=document,
            key_manager=key_manager,
            blob_store=blob_store,
            actor="provider",
        )


def test_sha256_hex_matches_hashlib() -> None:
    data = b"some bytes"
    assert service.sha256_hex(data) == hashlib.sha256(data).hexdigest()


def test_swapping_blobs_between_two_documents_in_one_case_fails_to_decrypt(
    db_session: Session, tmp_path: Path
) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case = _make_case(db_session, key_manager)

    doc_a = service.store_document(
        db_session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=b"document A's content",
        actor="provider",
    )
    doc_b = service.store_document(
        db_session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="coi",
        content=b"document B's content",
        actor="provider",
    )

    # Swap which ciphertext each Document row points at - same case, same
    # data key, but each blob's AAD is bound to the *other* document's id
    # and content hash.
    doc_a.storage_ref, doc_b.storage_ref = doc_b.storage_ref, doc_a.storage_ref

    with pytest.raises(InvalidTag):
        service.read_document(
            db_session,
            case=case,
            document=doc_a,
            key_manager=key_manager,
            blob_store=blob_store,
            actor="reviewer",
        )
    with pytest.raises(InvalidTag):
        service.read_document(
            db_session,
            case=case,
            document=doc_b,
            key_manager=key_manager,
            blob_store=blob_store,
            actor="reviewer",
        )


def test_identical_content_in_two_cases_does_not_collide_in_the_blob_store(
    db_session: Session, tmp_path: Path
) -> None:
    """storage_ref is the document id, not the content hash - otherwise
    two cases uploading byte-identical content would overwrite each
    other's blob (LocalBlobStore has no notion of "case")."""
    key_manager = LocalKeyManager(tmp_path / "master.key")
    blob_store = LocalBlobStore(tmp_path / "blobs")
    case_a = _make_case(db_session, key_manager)
    case_b = _make_case(db_session, key_manager)
    identical_content = b"byte-identical content uploaded to two different cases"

    doc_a = service.store_document(
        db_session,
        case=case_a,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=identical_content,
        actor="provider",
    )
    doc_b = service.store_document(
        db_session,
        case=case_b,
        key_manager=key_manager,
        blob_store=blob_store,
        slot="license",
        content=identical_content,
        actor="provider",
    )

    assert doc_a.sha256 == doc_b.sha256  # same content...
    assert doc_a.storage_ref != doc_b.storage_ref  # ...but distinct blobs

    for case, document in ((case_a, doc_a), (case_b, doc_b)):
        assert (
            service.read_document(
                db_session,
                case=case,
                document=document,
                key_manager=key_manager,
                blob_store=blob_store,
                actor="reviewer",
            )
            == identical_content
        )


def test_swapping_a_wrapped_key_between_two_cases_fails_to_unwrap(
    db_session: Session, tmp_path: Path
) -> None:
    key_manager = LocalKeyManager(tmp_path / "master.key")
    case_a = _make_case(db_session, key_manager)
    case_b = _make_case(db_session, key_manager)

    with pytest.raises(InvalidTag):
        key_manager.unwrap_key(case_a.wrapped_data_key, aad=str(case_b.id).encode())

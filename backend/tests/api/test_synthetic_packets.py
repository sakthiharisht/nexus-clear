"""Integration tests against the real generator output in
eval/fixtures/packets/ (not hand-written byte strings) - the actual
rendered PDFs a synthetic provider would upload, exercised through the
full API -> encrypt -> store -> audit -> decrypt round trip.

CLAUDE.md invariant 4 ("never log document text, extracted PII, or
secrets") is checked here at the API/audit-log boundary, on top of the
vault-layer check in tests/vault/test_service.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.orm import AuditLog, Case, Document
from app.core.redact import contains_sensitive_pattern
from app.vault import service
from tests.api.conftest import VaultComponents

_PACKETS_ROOT = Path(__file__).resolve().parents[3] / "eval" / "fixtures" / "packets"
_CLEAN_PACKET = _PACKETS_ROOT / "clean-1"

# From eval/fixtures/ground_truth.json's clean-1 "facts" - the PII baked
# into clean-1's rendered license.pdf/coi.pdf by the generator.
_PACKET_PII = ("Christopher Lee", "LPC-100000")


def _create_case(client: TestClient) -> dict:
    response = client.post(
        "/cases",
        json={
            "payer": "BCBSTX",
            "provider_type": "LPC",
            "provider_profile": {"legal_name": "Christopher Lee", "npi": "1000000004"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_real_clean_packet_fills_the_checklist(api_client: TestClient) -> None:
    case = _create_case(api_client)
    for slot in ("license", "coi", "cv", "education", "w9"):
        content = (_CLEAN_PACKET / f"{slot}.pdf").read_bytes()
        response = api_client.post(
            f"/cases/{case['id']}/documents",
            params={"slot": slot},
            files={"file": (f"{slot}.pdf", content, "application/pdf")},
        )
        assert response.status_code == 201, response.text

    checklist = api_client.get(f"/cases/{case['id']}/checklist").json()
    assert checklist["missing_required_slots"] == []
    assert all(s["uploaded"] for s in checklist["slots"])


def test_an_uploaded_packet_document_round_trips_through_the_vault(
    api_client: TestClient, vault_components: VaultComponents, db_session: Session
) -> None:
    case = _create_case(api_client)
    original = (_CLEAN_PACKET / "license.pdf").read_bytes()

    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        files={"file": ("license.pdf", original, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["id"]

    document = db_session.get(Document, document_id)
    assert document is not None
    case_row = db_session.get(Case, case["id"])
    assert case_row is not None

    decrypted = service.read_document(
        db_session,
        case=case_row,
        document=document,
        key_manager=vault_components.key_manager,
        blob_store=vault_components.blob_store,
        actor="reviewer",
    )
    assert decrypted == original


def test_the_stored_blob_is_encrypted_at_rest_not_the_raw_pdf(
    api_client: TestClient, vault_components: VaultComponents, db_session: Session
) -> None:
    original = (_CLEAN_PACKET / "license.pdf").read_bytes()
    case = _create_case(api_client)
    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        files={"file": ("license.pdf", original, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    document = db_session.get(Document, response.json()["id"])
    assert document is not None

    stored = vault_components.blob_store.get(document.storage_ref)
    assert stored != original
    for pii in _PACKET_PII:
        assert pii.encode() not in stored


def test_audit_log_rows_never_contain_document_text_or_pii(
    api_client: TestClient, vault_components: VaultComponents, db_session: Session
) -> None:
    case = _create_case(api_client)
    for slot in ("license", "coi"):
        content = (_CLEAN_PACKET / f"{slot}.pdf").read_bytes()
        response = api_client.post(
            f"/cases/{case['id']}/documents",
            params={"slot": slot},
            files={"file": (f"{slot}.pdf", content, "application/pdf")},
        )
        assert response.status_code == 201, response.text
        document = db_session.get(Document, response.json()["id"])
        assert document is not None
        case_row = db_session.get(Case, case["id"])
        assert case_row is not None
        service.read_document(
            db_session,
            case=case_row,
            document=document,
            key_manager=vault_components.key_manager,
            blob_store=vault_components.blob_store,
            actor="reviewer",
        )

    rows = db_session.query(AuditLog).filter_by(case_id=case["id"]).all()
    assert len(rows) == 4  # 2 uploads + 2 reads
    for row in rows:
        serialized = json.dumps(row.detail)
        for pii in _PACKET_PII:
            assert pii not in serialized


def test_no_document_text_or_pii_in_process_logs(
    api_client: TestClient,
    vault_components: VaultComponents,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exercises the real upload -> read path (app/vault/service.py's
    logger.info calls, added for this test to have something real to
    check) and asserts no captured log record contains the clean-1
    packet's PII or anything SSN/TIN-shaped - clean-1's own w9.pdf has
    a literal "TIN: 000-xx-xxxx" line (app/eval/generator/provider.py),
    so this also exercises app/core/redact.py's detector against real
    rendered document content, not a hand-written example.
    """
    caplog.set_level(logging.INFO, logger="app.vault.service")
    case = _create_case(api_client)
    content = (_CLEAN_PACKET / "w9.pdf").read_bytes()

    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "w9"},
        files={"file": ("w9.pdf", content, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    document = db_session.get(Document, response.json()["id"])
    assert document is not None
    case_row = db_session.get(Case, case["id"])
    assert case_row is not None

    service.read_document(
        db_session,
        case=case_row,
        document=document,
        key_manager=vault_components.key_manager,
        blob_store=vault_components.blob_store,
        actor="reviewer",
    )

    assert len(caplog.records) >= 2  # upload + read - not a vacuous pass
    for record in caplog.records:
        message = record.getMessage()
        assert not contains_sensitive_pattern(message)
        for pii in _PACKET_PII:
            assert pii not in message

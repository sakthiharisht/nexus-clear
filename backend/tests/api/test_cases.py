"""Tests for the intake API (SPEC.md section 8): create case, checklist,
upload document. tests/api/test_synthetic_packets.py covers the full
upload -> encrypt -> store -> audit -> decrypt round trip using the real
generator's rendered documents; this file is the API contract itself.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

_MINIMAL_PDF = b"%PDF-1.4\n%synthetic test content, not a real document\n"
_MINIMAL_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_NOT_A_PDF = b"this is plain text, not a PDF"


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


def test_create_case(api_client: TestClient) -> None:
    body = _create_case(api_client)
    assert body["payer"] == "BCBSTX"
    assert body["provider_type"] == "LPC"
    assert body["state"] == "created"
    assert body["provider_profile"]["legal_name"] == "Christopher Lee"


def test_create_case_defaults_target_date_from_the_rule_pack(api_client: TestClient) -> None:
    import datetime

    body = _create_case(api_client)
    target = datetime.date.fromisoformat(body["target_date"])
    # rules/tx_bcbstx_lpc.yaml: target_date_default_offset_days: 14.
    assert (target - datetime.date.today()).days == 14


def test_create_case_accepts_an_explicit_target_date(api_client: TestClient) -> None:
    response = api_client.post(
        "/cases",
        json={
            "payer": "BCBSTX",
            "provider_type": "LPC",
            "provider_profile": {"legal_name": "Someone"},
            "target_date": "2027-01-01",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["target_date"] == "2027-01-01"


def test_get_case(api_client: TestClient) -> None:
    created = _create_case(api_client)
    response = api_client.get(f"/cases/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_unknown_case_is_404(api_client: TestClient) -> None:
    response = api_client.get(f"/cases/{uuid4()}")
    assert response.status_code == 404


def test_checklist_lists_the_rule_packs_required_slots(api_client: TestClient) -> None:
    case = _create_case(api_client)
    response = api_client.get(f"/cases/{case['id']}/checklist")
    assert response.status_code == 200
    body = response.json()
    slots = {s["slot"]: s for s in body["slots"]}
    assert set(slots) == {"license", "coi", "cv", "education", "w9"}
    assert slots["license"]["required"] is True
    assert slots["w9"]["required"] is False
    assert all(not s["uploaded"] for s in body["slots"])
    assert set(body["missing_required_slots"]) == {"license", "coi", "cv", "education"}


def test_checklist_on_unknown_case_is_404(api_client: TestClient) -> None:
    assert api_client.get(f"/cases/{uuid4()}/checklist").status_code == 404


def test_upload_document_and_see_it_in_the_checklist(api_client: TestClient) -> None:
    case = _create_case(api_client)
    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        files={"file": ("license.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["slot"] == "license"
    assert document["case_id"] == case["id"]
    assert len(document["sha256"]) == 64

    checklist = api_client.get(f"/cases/{case['id']}/checklist").json()
    slots = {s["slot"]: s for s in checklist["slots"]}
    assert slots["license"]["uploaded"] is True
    assert slots["license"]["document_id"] == document["id"]
    assert "license" not in checklist["missing_required_slots"]


def test_upload_accepts_a_png(api_client: TestClient) -> None:
    case = _create_case(api_client)
    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        files={"file": ("scan.png", _MINIMAL_PNG, "image/png")},
    )
    assert response.status_code == 201, response.text


def test_upload_to_unknown_slot_is_rejected(api_client: TestClient) -> None:
    case = _create_case(api_client)
    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "not-a-real-slot"},
        files={"file": ("x.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 400


def test_upload_rejects_a_file_that_doesnt_match_any_allowed_magic_bytes(
    api_client: TestClient,
) -> None:
    case = _create_case(api_client)
    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        # Lying Content-Type header - the server sniffs real bytes, not this.
        files={"file": ("fake.pdf", _NOT_A_PDF, "application/pdf")},
    )
    assert response.status_code == 415


def test_upload_rejects_oversize_files(api_client: TestClient) -> None:
    from app.core.config import settings

    case = _create_case(api_client)
    oversized = b"%PDF-1.4\n" + b"0" * settings.max_upload_size_bytes
    response = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_rejects_a_duplicate_hash_in_the_same_case(api_client: TestClient) -> None:
    case = _create_case(api_client)
    first = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "license"},
        files={"file": ("license.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert first.status_code == 201

    duplicate = api_client.post(
        f"/cases/{case['id']}/documents",
        params={"slot": "coi"},  # even into a different slot - same content
        files={"file": ("license-again.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert duplicate.status_code == 409


def test_same_content_is_allowed_across_different_cases(api_client: TestClient) -> None:
    case_a = _create_case(api_client)
    case_b = _create_case(api_client)
    for case in (case_a, case_b):
        response = api_client.post(
            f"/cases/{case['id']}/documents",
            params={"slot": "license"},
            files={"file": ("license.pdf", _MINIMAL_PDF, "application/pdf")},
        )
        assert response.status_code == 201


def test_upload_to_unknown_case_is_404(api_client: TestClient) -> None:
    response = api_client.post(
        f"/cases/{uuid4()}/documents",
        params={"slot": "license"},
        files={"file": ("x.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 404

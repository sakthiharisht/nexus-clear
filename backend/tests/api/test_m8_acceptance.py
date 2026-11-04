"""M8 acceptance (SPEC.md section 7.7-7.9 / section 14): the full
pipeline, through the real API, from a defective case to an attested
packet - Classify -> Extract -> Reconcile -> Validate -> Escalate ->
human review -> attest -> packet.

"Defective" here is an intake-side name mismatch, not a document
defect: clean-1's real rendered documents (license holder "Christopher
Lee") are uploaded against a case whose intake profile says "John
Smyth" - a genuine mismatch the Investigator can't auto-resolve, which
is exactly the kind of uncertainty Escalate is for (unlike a hard
document defect such as D09's wrong-document-in-slot, which has no
confidence score to threshold and correctly stays an unreviewable
blocker until the provider fixes the upload - not something this test
tries to clear).

Two layers, same pattern as every other model-backed test in this
project (tests/reconcile/test_acceptance.py):
1. Replay-mode (`test_..._replay`, no API key, runs in CI): reads the
   real recordings committed alongside every other model_cache entry.
2. Live (`test_..._live`, skipif no key): the same assertions against
   fresh real calls - also how the replay fixture was first seeded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import (
    get_extractor,
    get_fallback_backend,
    get_investigator,
    get_phraser,
    get_primary_backend,
)
from app.backends.factory import build_extractor, build_investigator, build_primary_and_fallback
from app.core.config import settings as real_settings
from app.core.orm import ReviewItem
from app.main import app
from app.report.factory import build_phraser

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
_HAS_ANTHROPIC_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

REPO_ROOT = Path(__file__).resolve().parents[3]
_CLEAN_PACKET = REPO_ROOT / "eval" / "fixtures" / "packets" / "clean-1"
_SLOTS = ("license", "coi", "cv", "education", "w9")


def _create_case(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/cases",
        json={
            "payer": "BCBSTX",
            "provider_type": "LPC",
            "provider_profile": {"legal_name": "John Smyth", "npi": "1000000004"},
            "target_date": "2026-11-17",
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _upload_clean_1(client: TestClient, case_id: str) -> None:
    for slot in _SLOTS:
        content = (_CLEAN_PACKET / f"{slot}.pdf").read_bytes()
        response = client.post(
            f"/cases/{case_id}/documents",
            params={"slot": slot},
            files={"file": (f"{slot}.pdf", content, "application/pdf")},
        )
        assert response.status_code == 201, response.text


def _run_acceptance_flow(client: TestClient, db_session: Session) -> None:
    case = _create_case(client)
    case_id = case["id"]
    _upload_clean_1(client, case_id)

    run_response = client.post(f"/cases/{case_id}/run")
    assert run_response.status_code == 200, run_response.text
    run_result = run_response.json()
    assert run_result["findings"]
    assert run_result["escalated_finding_ids"]

    reviews_response = client.get("/reviews", params={"case_id": case_id})
    assert reviews_response.status_code == 200
    reviews = reviews_response.json()
    assert reviews, "the name mismatch must have produced at least one review item"
    assert all(r["status"] == "pending" for r in reviews)

    # Attestation must be blocked while any review item is unresolved
    # and/or an open blocker remains.
    blocked = client.post(
        f"/cases/{case_id}/attest",
        json={"confirmed": True, "attested_by": "reviewer-1", "typed_name": "Reviewer One"},
    )
    assert blocked.status_code == 409

    for review in reviews:
        detail = client.get(f"/reviews/{review['id']}")
        assert detail.status_code == 200
        assert detail.json()["finding"]["evidence"]  # "view evidence"

        resolve = client.post(
            f"/reviews/{review['id']}/resolve",
            json={
                "decision": "override",
                "override_status": "pass",
                "note": "Confirmed same person via a secondary ID check.",
                "resolved_by": "reviewer-1",
            },
        )
        assert resolve.status_code == 200, resolve.text
        assert resolve.json()["status"] == "resolved"

    report = client.get(f"/cases/{case_id}/report")
    assert report.status_code == 200
    report_body = report.json()
    assert report_body["entries"]
    for entry in report_body["entries"]:
        assert entry["finding_id"]  # every sentence maps to a finding_id

    review_rows = db_session.query(ReviewItem).filter_by(case_id=case_id).all()
    assert review_rows and all(row.status == "resolved" for row in review_rows)

    attest = client.post(
        f"/cases/{case_id}/attest",
        json={"confirmed": True, "attested_by": "reviewer-1", "typed_name": "Reviewer One"},
    )
    assert attest.status_code == 200, attest.text
    attest_body = attest.json()
    assert attest_body["packet_hash"]

    packet_response = client.get(f"/cases/{case_id}/packet")
    assert packet_response.status_code == 200
    packet = packet_response.json()
    assert packet["license"].get("holder_name") == "Christopher Lee"
    assert packet["label"].startswith("CAQH-style")

    # Re-attesting is rejected, not silently repeated.
    again = client.post(
        f"/cases/{case_id}/attest",
        json={"confirmed": True, "attested_by": "reviewer-1", "typed_name": "Reviewer One"},
    )
    assert again.status_code == 409


def test_defective_case_runs_end_to_end_to_an_attested_packet_replay(
    api_client: TestClient, db_session: Session
) -> None:
    """No ANTHROPIC_API_KEY required - every model call below resolves
    from the real, already-recorded model_cache committed alongside
    every other fixture in this project."""
    _run_acceptance_flow(api_client, db_session)


@pytest.mark.skipif(not _HAS_ANTHROPIC_KEY, reason="no ANTHROPIC_API_KEY in backend/.env")
def test_defective_case_runs_end_to_end_to_an_attested_packet_live(
    api_client: TestClient, db_session: Session
) -> None:
    record_settings = real_settings.model_copy(update={"model_cache_mode": "record"})
    primary, fallback = build_primary_and_fallback(record_settings)
    overridden_deps = (
        get_primary_backend,
        get_fallback_backend,
        get_extractor,
        get_investigator,
        get_phraser,
    )
    app.dependency_overrides[get_primary_backend] = lambda: primary
    app.dependency_overrides[get_fallback_backend] = lambda: fallback
    app.dependency_overrides[get_extractor] = lambda: build_extractor(record_settings)
    app.dependency_overrides[get_investigator] = lambda: build_investigator(record_settings)
    app.dependency_overrides[get_phraser] = lambda: build_phraser(record_settings)
    try:
        _run_acceptance_flow(api_client, db_session)
    finally:
        for dep in overridden_deps:
            app.dependency_overrides.pop(dep, None)


def test_attest_requires_an_explicit_confirmation_payload(api_client: TestClient) -> None:
    case = _create_case(api_client)
    missing_confirmed = api_client.post(
        f"/cases/{case['id']}/attest",
        json={"attested_by": "reviewer-1", "typed_name": "Reviewer One"},
    )
    assert missing_confirmed.status_code == 422

    confirmed_false = api_client.post(
        f"/cases/{case['id']}/attest",
        json={"confirmed": False, "attested_by": "reviewer-1", "typed_name": "Reviewer One"},
    )
    assert confirmed_false.status_code == 422

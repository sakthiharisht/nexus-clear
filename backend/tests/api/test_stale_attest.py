"""Pre-M9 fix #2: attestation must refuse (409) whenever the case's
last run predates something that could have changed what the packet/
findings should say - a document upload, or a review resolution.
tests/api/test_m8_acceptance.py's main flow exercises the resolution
half live (via a real escalation); this file covers the boundary
cases directly against a clean, no-escalation run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.orm import Case

REPO_ROOT = Path(__file__).resolve().parents[3]
_CLEAN_PACKET = REPO_ROOT / "eval" / "fixtures" / "packets" / "clean-1"
_SLOTS = ("license", "coi", "cv", "education", "w9")


def _create_case(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/cases",
        json={
            "payer": "BCBSTX",
            "provider_type": "LPC",
            "provider_profile": {"legal_name": "Christopher Lee", "npi": "1000000004"},
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


def _attest(client: TestClient, case: dict[str, Any]) -> int:
    response = client.post(
        f"/cases/{case['id']}/attest",
        json={"confirmed": True, "attested_by": "reviewer-1", "typed_name": "Reviewer One"},
        headers={"X-Provider-Token": case["provider_token"]},
    )
    return response.status_code


def test_attest_fails_if_the_case_was_never_run(api_client: TestClient) -> None:
    case = _create_case(api_client)
    _upload_clean_1(api_client, case["id"])
    assert _attest(api_client, case) == 409


def test_attest_succeeds_right_after_a_clean_run_with_no_open_issues(
    api_client: TestClient,
) -> None:
    case = _create_case(api_client)
    _upload_clean_1(api_client, case["id"])
    run_response = api_client.post(f"/cases/{case['id']}/run")
    assert run_response.status_code == 200, run_response.text
    assert run_response.json()["escalated_finding_ids"] == []

    assert _attest(api_client, case) == 200


def test_attest_fails_after_an_upload_that_postdates_the_last_run(
    api_client: TestClient, db_session: Session
) -> None:
    case = _create_case(api_client)
    _upload_clean_1(api_client, case["id"])
    run_response = api_client.post(f"/cases/{case['id']}/run")
    assert run_response.status_code == 200, run_response.text

    # The test harness runs everything in one enclosing transaction, so
    # Postgres's func.now() (Document.uploaded_at's server_default) is
    # pinned to the transaction's start for every row - a real second
    # upload here would not actually land "after" last_run_at the way
    # it would across separate request transactions in production.
    # Rewinding last_run_at models the same relationship (an upload
    # exists that the last run predates) without fighting that clock.
    case_row = db_session.get(Case, case["id"])
    assert case_row is not None
    case_row.last_run_at = datetime(2000, 1, 1, tzinfo=UTC)
    db_session.commit()

    assert _attest(api_client, case) == 409

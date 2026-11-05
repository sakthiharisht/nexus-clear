"""Reviewer queue API tests (SPEC.md section 7.9) not already covered
by the full acceptance flow (tests/api/test_m8_acceptance.py): 404s,
the override_status requirement, and the already-resolved conflict.
"""

from __future__ import annotations

import secrets
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings as real_settings
from app.core.orm import Case, FindingRecord, ReviewItem
from app.vault import service
from tests.api.conftest import VaultComponents

_REVIEWER_HEADERS = {"X-Reviewer-Token": real_settings.reviewer_token}


def _seed_case_with_review_item(
    db_session: Session, vault_components: VaultComponents
) -> tuple[Case, ReviewItem]:
    case_id = uuid4()
    case = Case(
        id=case_id,
        provider_profile={"legal_name": "Christopher Lee", "npi": "1000000004"},
        payer="BCBSTX",
        provider_type="LPC",
        target_date="2026-11-17",
        wrapped_data_key=service.create_wrapped_case_key(
            vault_components.key_manager, case_id=case_id
        ),
        provider_token=secrets.token_urlsafe(24),
    )
    db_session.add(case)
    db_session.flush()

    record = FindingRecord(
        case_id=case.id,
        rule_pack_version="test",
        finding={
            "finding_id": "R-LIC-004",
            "rule_id": "R-LIC-004",
            "status": "fail",
            "severity": "blocker",
            "evidence": [{"kind": "document", "quote": "a quote"}],
            "rule_source": {
                "source_id": "s",
                "last_verified": "2026-01-01",
                "needs_verification": False,
            },
            "confidence": 0.4,
            "decided_by": "code",
        },
    )
    db_session.add(record)
    db_session.flush()

    review_item = ReviewItem(case_id=case.id, finding_id=record.id, status="pending")
    db_session.add(review_item)
    db_session.commit()
    return case, review_item


def test_get_unknown_review_is_404(api_client: TestClient) -> None:
    assert api_client.get(f"/reviews/{uuid4()}").status_code == 404


def test_resolve_unknown_review_is_404(api_client: TestClient) -> None:
    response = api_client.post(
        f"/reviews/{uuid4()}/resolve",
        json={"decision": "confirm", "note": "x", "resolved_by": "reviewer-1"},
        headers=_REVIEWER_HEADERS,
    )
    assert response.status_code == 404


def test_resolve_requires_the_reviewer_token(
    api_client: TestClient, db_session: Session, vault_components: VaultComponents
) -> None:
    _case, review_item = _seed_case_with_review_item(db_session, vault_components)
    response = api_client.post(
        f"/reviews/{review_item.id}/resolve",
        json={"decision": "confirm", "note": "x", "resolved_by": "reviewer-1"},
        headers={"X-Reviewer-Token": "wrong-token"},
    )
    assert response.status_code == 403


def test_override_without_override_status_is_rejected(
    api_client: TestClient, db_session: Session, vault_components: VaultComponents
) -> None:
    _case, review_item = _seed_case_with_review_item(db_session, vault_components)
    response = api_client.post(
        f"/reviews/{review_item.id}/resolve",
        json={"decision": "override", "note": "x", "resolved_by": "reviewer-1"},
        headers=_REVIEWER_HEADERS,
    )
    assert response.status_code == 400


def test_resolving_an_already_resolved_item_is_a_conflict(
    api_client: TestClient, db_session: Session, vault_components: VaultComponents
) -> None:
    _case, review_item = _seed_case_with_review_item(db_session, vault_components)
    first = api_client.post(
        f"/reviews/{review_item.id}/resolve",
        json={"decision": "confirm", "note": "x", "resolved_by": "reviewer-1"},
        headers=_REVIEWER_HEADERS,
    )
    assert first.status_code == 200

    second = api_client.post(
        f"/reviews/{review_item.id}/resolve",
        json={"decision": "confirm", "note": "y", "resolved_by": "reviewer-2"},
        headers=_REVIEWER_HEADERS,
    )
    assert second.status_code == 409


def test_confirm_keeps_the_original_status_but_marks_decided_by_human(
    api_client: TestClient, db_session: Session, vault_components: VaultComponents
) -> None:
    _case, review_item = _seed_case_with_review_item(db_session, vault_components)
    response = api_client.post(
        f"/reviews/{review_item.id}/resolve",
        json={"decision": "confirm", "note": "confirmed correct", "resolved_by": "reviewer-1"},
        headers=_REVIEWER_HEADERS,
    )
    assert response.status_code == 200

    record = db_session.get(FindingRecord, review_item.finding_id)
    assert record is not None
    assert record.finding["status"] == "fail"
    assert record.finding["decided_by"] == "human"


def test_override_changes_the_findings_status(
    api_client: TestClient, db_session: Session, vault_components: VaultComponents
) -> None:
    _case, review_item = _seed_case_with_review_item(db_session, vault_components)
    response = api_client.post(
        f"/reviews/{review_item.id}/resolve",
        json={
            "decision": "override",
            "override_status": "pass",
            "note": "confirmed same person",
            "resolved_by": "reviewer-1",
        },
        headers=_REVIEWER_HEADERS,
    )
    assert response.status_code == 200

    record = db_session.get(FindingRecord, review_item.finding_id)
    assert record is not None
    assert record.finding["status"] == "pass"
    assert record.finding["decided_by"] == "human"


def test_list_reviews_filters_by_case_id(
    api_client: TestClient, db_session: Session, vault_components: VaultComponents
) -> None:
    case, review_item = _seed_case_with_review_item(db_session, vault_components)
    other_case, _ = _seed_case_with_review_item(db_session, vault_components)

    response = api_client.get("/reviews", params={"case_id": str(case.id)})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(review_item.id)
    assert all(row["case_id"] != str(other_case.id) for row in body)

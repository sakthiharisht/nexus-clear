"""Pre-M9 fix #1: image-only documents (no text layer) now go through
the vision Extract path in the live orchestrator instead of being
skipped - cached on the image's own sha256 (app/backends/extract_cache.py),
same as every other extract call. benign-2-rotated-scan's real license
scan (a genuine rotated, but readable, image - app/eval/generator's
"benign" kind, not "defective") is the real-world case this proves:

- A field read off the image comes back "known" (the model reported a
  value with a quote) but quote_verified=False (there's no text layer
  for code to check that quote against) - a verified-false citation,
  CLAUDE.md invariant 2's "no supporting quote is unknown" rule's
  cousin for images specifically (app/core/citations.py's verify_field
  docstring).
- That unverified-but-known field feeds a blocker rule (license.*),
  which must then reach the reviewer queue via unverified_quote_on_blocker
  - previously dead code in the live path, since extraction was skipped
  entirely for any image-only document.

Two layers, same pattern as every other model-backed test in this
project: replay (CI, no key) reads the real recording committed
alongside every other fixture; live (skipif no key) is how it was
seeded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_extractor, get_fallback_backend, get_primary_backend
from app.backends.factory import build_extractor, build_primary_and_fallback
from app.core.config import settings as real_settings
from app.core.orm import Document, Extraction, FindingRecord, ReviewItem
from app.main import app

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
_HAS_ANTHROPIC_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKET = REPO_ROOT / "eval" / "fixtures" / "packets" / "benign-2-rotated-scan"
# The license scan is a static, committed fixture (tests/fixtures/vision/),
# not read from eval/fixtures/packets/ like the other four documents:
# that tree is gitignored and regenerated per run, and Pillow's PNG
# compression isn't byte-identical across platforms (unlike reportlab's
# PDF output, which is) - a cache key derived from this image's sha256
# would miss in CI otherwise, even though the pixels are identical.
_VISION_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "vision"
_FILES_BY_SLOT = {
    "license": (_VISION_FIXTURES / "benign_2_license_scan.png", "image/png"),
    "coi": (_PACKET / "coi.pdf", "application/pdf"),
    "cv": (_PACKET / "cv.pdf", "application/pdf"),
    "education": (_PACKET / "education.pdf", "application/pdf"),
    "w9": (_PACKET / "w9.pdf", "application/pdf"),
}


def _create_case(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/cases",
        json={
            "payer": "BCBSTX",
            "provider_type": "LPC",
            "provider_profile": {"legal_name": "Ashley Warren", "npi": "1000000038"},
            "target_date": "2026-11-17",
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _upload_benign_2(client: TestClient, case_id: str) -> None:
    for slot, (path, content_type) in _FILES_BY_SLOT.items():
        content = path.read_bytes()
        response = client.post(
            f"/cases/{case_id}/documents",
            params={"slot": slot},
            files={"file": (path.name, content, content_type)},
        )
        assert response.status_code == 201, response.text


def _run_vision_flow(client: TestClient, db_session: Session) -> None:
    case = _create_case(client)
    case_id = case["id"]
    _upload_benign_2(client, case_id)

    run_response = client.post(f"/cases/{case_id}/run")
    assert run_response.status_code == 200, run_response.text
    run_result = run_response.json()
    assert run_result["findings"]

    license_document = (
        db_session.query(Document).filter_by(case_id=UUID(case_id), slot="license").one()
    )
    extraction = (
        db_session.query(Extraction).filter_by(document_id=license_document.id).one_or_none()
    )
    assert extraction is not None, "the scanned license must still go through Extract via vision"
    assert extraction.schema_version == "license"

    known_unverified_fields = [
        name
        for name, field in extraction.fields.items()
        if isinstance(field, dict)
        and field.get("status") == "known"
        and not field.get("quote_verified")
    ]
    assert known_unverified_fields, (
        "a vision-read field must be known-but-unverified (no text layer to "
        "check its quote against) - got "
        f"{extraction.fields}"
    )

    review_items = db_session.query(ReviewItem).filter_by(case_id=UUID(case_id)).all()
    assert review_items, "the unverified quote on a blocker must reach the reviewer queue"

    escalated_license_blocker = False
    for item in review_items:
        record = db_session.get(FindingRecord, item.finding_id)
        assert record is not None
        finding = record.finding
        rule_id = finding["rule_id"]
        is_license_blocker = (
            isinstance(rule_id, str)
            and rule_id.startswith("R-LIC")
            and finding["severity"] == "blocker"
        )
        if is_license_blocker:
            escalated_license_blocker = True
    assert escalated_license_blocker, (
        "unverified_quote_on_blocker must be reachable end to end: at least "
        "one license blocker should be in the queue"
    )


def test_a_rotated_scan_reaches_the_reviewer_queue_via_vision_replay(
    api_client: TestClient, db_session: Session
) -> None:
    """No ANTHROPIC_API_KEY required - reads the real, already-recorded
    vision extraction committed alongside every other fixture."""
    _run_vision_flow(api_client, db_session)


@pytest.mark.skipif(not _HAS_ANTHROPIC_KEY, reason="no ANTHROPIC_API_KEY in backend/.env")
def test_a_rotated_scan_reaches_the_reviewer_queue_via_vision_live(
    api_client: TestClient, db_session: Session
) -> None:
    record_settings = real_settings.model_copy(update={"model_cache_mode": "record"})
    primary, fallback = build_primary_and_fallback(record_settings)
    overridden_deps = (get_primary_backend, get_fallback_backend, get_extractor)
    app.dependency_overrides[get_primary_backend] = lambda: primary
    app.dependency_overrides[get_fallback_backend] = lambda: fallback
    app.dependency_overrides[get_extractor] = lambda: build_extractor(record_settings)
    try:
        _run_vision_flow(api_client, db_session)
    finally:
        for dep in overridden_deps:
            app.dependency_overrides.pop(dep, None)

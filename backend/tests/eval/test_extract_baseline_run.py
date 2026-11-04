from __future__ import annotations

import json
from pathlib import Path

from app.eval.extract_baseline_run import run_extract_baseline

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"


def test_run_extract_baseline_scores_a_clean_license_correctly() -> None:
    result = run_extract_baseline(GROUND_TRUTH, FIXTURES_ROOT)
    license_doc = next(
        d for d in result.documents if d.packet_id == "clean-1" and d.slot == "license"
    )
    holder_name = next(f for f in license_doc.field_results if f.field == "license.holder_name")
    assert holder_name.status == "known"
    assert holder_name.correct is True
    assert holder_name.quote_verified is True


def test_run_extract_baseline_skips_the_license_slot_when_a_cv_is_misfiled_there() -> None:
    result = run_extract_baseline(GROUND_TRUTH, FIXTURES_ROOT)
    license_docs = [
        d for d in result.documents if d.packet_id == "defective-7" and d.slot == "license"
    ]
    assert license_docs == []


def test_run_extract_baseline_reports_unknown_for_an_illegible_scan() -> None:
    """benign-2-rotated-scan's license is a PNG with no text layer -
    baseline has no OCR, so every license field must come back
    unknown, never a guess (the slot is still scored - ground truth
    confirms it genuinely is a license, just unreadable)."""
    result = run_extract_baseline(GROUND_TRUTH, FIXTURES_ROOT)
    license_doc = next(
        d
        for d in result.documents
        if d.packet_id == "benign-2-rotated-scan" and d.slot == "license"
    )
    assert all(f.status == "unknown" for f in license_doc.field_results)
    assert all(f.correct is False for f in license_doc.field_results)


def test_run_extract_baseline_mode_name() -> None:
    result = run_extract_baseline(GROUND_TRUTH, FIXTURES_ROOT)
    assert result.mode == "extract-baseline"

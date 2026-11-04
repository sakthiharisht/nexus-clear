from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    CvPositionExtraction,
    ExtractedField,
    ExtractInput,
    ExtractionResult,
    LicenseExtraction,
)
from app.eval.extract_run import build_extract_input, run_extract

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"


def _packet(packet_id: str) -> dict[str, Any]:
    return next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == packet_id)


def _field(value: str | None, quote: str | None) -> ExtractedField:
    return ExtractedField(value=value, confidence=0.9, page=1, quote=quote)


class _StubExtractor:
    name = "claude"
    prompt_version = "test"

    def __init__(self, simulated: bool = False) -> None:
        self.inputs: list[ExtractInput] = []
        self._simulated = simulated

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        self.inputs.append(extract_input)
        if extract_input.kind == "license":
            return ExtractionResult(
                kind="license",
                fields=LicenseExtraction(
                    holder_name=_field("Christopher Lee", "Holder name: Christopher Lee")
                ),
                simulated=self._simulated,
            )
        if extract_input.kind == "coi":
            return ExtractionResult(
                kind="coi", fields=CoiExtraction(), simulated=self._simulated
            )
        return ExtractionResult(kind="cv", fields=CvExtraction(), simulated=self._simulated)


class _RaisingExtractor:
    name = "claude"
    prompt_version = "test"

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        raise ValueError("Claude did not return a parsed structured output")


def test_build_extract_input_reads_the_full_text_layer() -> None:
    extract_input = build_extract_input(_packet("clean-1"), "license", "license", FIXTURES_ROOT)
    assert extract_input.kind == "license"
    assert "Christopher Lee" in extract_input.document_text


def test_run_extract_scores_a_correct_field_against_ground_truth() -> None:
    backend = _StubExtractor()
    result = run_extract(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-test", backend=backend
    )
    license_doc = next(
        d for d in result.documents if d.packet_id == "clean-1" and d.slot == "license"
    )
    holder_name = next(f for f in license_doc.field_results if f.field == "license.holder_name")
    assert holder_name.status == "known"
    assert holder_name.correct is True


def test_run_extract_skips_a_slot_whose_uploaded_document_is_not_that_schema() -> None:
    """defective-7 plants D09: the license slot actually holds a CV.
    There is no license to score against - this slot contributes
    nothing to license-field accuracy, matching M3 baseline's own
    gating (app/eval/baseline_extraction.py)."""
    backend = _StubExtractor()
    result = run_extract(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-test", backend=backend
    )
    license_docs = [
        d for d in result.documents if d.packet_id == "defective-7" and d.slot == "license"
    ]
    assert license_docs == []
    # The cv slot (the genuine CV, injected text and all) IS scored.
    cv_docs = [d for d in result.documents if d.packet_id == "defective-7" and d.slot == "cv"]
    assert len(cv_docs) == 1


def test_run_extract_covers_only_the_three_scored_slots_per_packet() -> None:
    backend = _StubExtractor()
    result = run_extract(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-test", backend=backend
    )
    slots = {d.slot for d in result.documents}
    assert slots == {"license", "coi", "cv"}


def test_run_extract_marks_mode_simulated_when_any_document_is_simulated() -> None:
    backend = _StubExtractor(simulated=True)
    result = run_extract(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-test", backend=backend
    )
    assert result.mode == "extract-test-SIMULATED"


def test_run_extract_handles_a_value_error_as_an_empty_unknown_document() -> None:
    backend = _RaisingExtractor()
    result = run_extract(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-test", backend=backend
    )
    assert len(result.documents) > 0
    assert all(d.field_results == [] for d in result.documents)


def test_cv_positions_score_each_position_independently() -> None:
    class _CvExtractor:
        name = "claude"
        prompt_version = "test"

        def extract(self, extract_input: ExtractInput) -> ExtractionResult:
            if extract_input.kind == "license":
                return ExtractionResult(kind="license", fields=LicenseExtraction())
            if extract_input.kind == "coi":
                return ExtractionResult(kind="coi", fields=CoiExtraction())
            return ExtractionResult(
                kind="cv",
                fields=CvExtraction(
                    positions=[
                        CvPositionExtraction(
                            title=_field("Associate Counselor", "Associate Counselor"),
                            employer=_field(
                                "Brown LLC Behavioral Health", "Brown LLC Behavioral Health"
                            ),
                            start=_field("2020-11-18", "2020-11-18"),
                            end=_field("2023-11-18", "2023-11-18"),
                        )
                    ]
                ),
            )

    result = run_extract(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-test", backend=_CvExtractor()
    )
    cv_doc = next(d for d in result.documents if d.packet_id == "clean-1" and d.slot == "cv")
    position_0_title = next(
        f for f in cv_doc.field_results if f.field == "cv.positions[0].title"
    )
    assert position_0_title.correct is True
    # clean-1 has two positions in ground truth; only one was returned -
    # position 1 is scored as a miss (unknown), not silently dropped.
    position_1_title = next(
        f for f in cv_doc.field_results if f.field == "cv.positions[1].title"
    )
    assert position_1_title.status == "unknown"
    assert position_1_title.correct is False


@pytest.mark.parametrize("packet_id", [p["packet_id"] for p in GROUND_TRUTH["packets"]])
def test_run_extract_does_not_crash_on_any_real_packet(packet_id: str) -> None:
    packet = _packet(packet_id)
    backend = _StubExtractor()
    run_extract(
        {"packets": [packet]}, FIXTURES_ROOT, mode_name="extract-test", backend=backend
    )

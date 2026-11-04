from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.backends.extract_cache import MissingFixtureError
from app.backends.extract_types import (
    ExtractedField,
    ExtractInput,
    ExtractionResult,
    LicenseExtraction,
)
from app.eval.extract_run import LICENSE_FIELDS
from app.eval.extract_vision_run import (
    build_vision_extract_input,
    run_extract_vision,
    run_extract_vision_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"


def _packet(packet_id: str) -> dict[str, Any]:
    return next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == packet_id)


def test_build_vision_extract_input_attaches_the_real_png_bytes() -> None:
    extract_input = build_vision_extract_input(_packet("benign-2-rotated-scan"), FIXTURES_ROOT)
    assert extract_input is not None
    assert extract_input.image_b64 is not None
    assert extract_input.image_media_type == "image/png"
    assert extract_input.document_text == ""


def test_build_vision_extract_input_is_none_for_a_text_layer_packet() -> None:
    assert build_vision_extract_input(_packet("clean-1"), FIXTURES_ROOT) is None


class _StubVisionExtractor:
    name = "claude"
    prompt_version = "test"

    def __init__(self, holder_name: str | None) -> None:
        self._holder_name = holder_name

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        assert extract_input.image_b64 is not None
        if self._holder_name is None:
            return ExtractionResult(kind="license", fields=LicenseExtraction())
        return ExtractionResult(
            kind="license",
            fields=LicenseExtraction(
                holder_name=ExtractedField(
                    value=self._holder_name,
                    confidence=0.9,
                    page=1,
                    quote=f"Holder name: {self._holder_name}",
                )
            ),
        )


def test_run_extract_vision_scores_both_image_only_license_slots() -> None:
    backend = _StubVisionExtractor(holder_name=None)
    result = run_extract_vision(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-vision-test", backend=backend
    )
    packet_ids = {d.packet_id for d in result.documents}
    assert packet_ids == {"benign-2-rotated-scan", "defective-7"}


def test_run_extract_vision_scores_a_correct_read_against_ground_truth() -> None:
    packet = _packet("benign-2-rotated-scan")
    true_holder_name = packet["facts"]["license"]["holder_name"]
    backend = _StubVisionExtractor(holder_name=true_holder_name)
    result = run_extract_vision(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-vision-test", backend=backend
    )
    doc = next(d for d in result.documents if d.packet_id == "benign-2-rotated-scan")
    holder_name_result = next(f for f in doc.field_results if f.field == "license.holder_name")
    assert holder_name_result.correct is True
    assert holder_name_result.quote_verified is False  # no text layer to verify against


def test_run_extract_vision_scores_defective_7_as_unknown_not_a_guess() -> None:
    """defective-7's license slot is actually an illegible CV scan
    (D09+D10) - a vision model reporting every field unknown here is
    correct behavior, not a scoring gap."""
    backend = _StubVisionExtractor(holder_name=None)
    result = run_extract_vision(
        GROUND_TRUTH, FIXTURES_ROOT, mode_name="extract-vision-test", backend=backend
    )
    doc = next(d for d in result.documents if d.packet_id == "defective-7")
    assert all(f.status == "unknown" for f in doc.field_results)
    # Ground truth's real license values are still used as `expected`
    # - correct is False only in the sense that nothing was known.
    assert any(f.expected is not None for f in doc.field_results)


class _RaisingVisionExtractor:
    name = "claude"
    prompt_version = "test"

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        raise MissingFixtureError("no cached response")


def test_run_extract_vision_handles_a_cache_miss_without_crashing() -> None:
    result = run_extract_vision(
        GROUND_TRUTH,
        FIXTURES_ROOT,
        mode_name="extract-vision-test",
        backend=_RaisingVisionExtractor(),
    )
    assert len(result.documents) == 2
    assert all(d.field_results == [] for d in result.documents)


def test_run_extract_vision_baseline_shows_zero_coverage_no_ocr() -> None:
    result = run_extract_vision_baseline(GROUND_TRUTH, FIXTURES_ROOT)
    assert len(result.documents) == 2
    for doc in result.documents:
        assert all(f.status == "unknown" for f in doc.field_results)
    fields_covered = {f.field for d in result.documents for f in d.field_results}
    assert fields_covered == {f"license.{name}" for name in LICENSE_FIELDS}

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    CvPositionExtraction,
    ExtractedField,
    ExtractInput,
    ExtractionResult,
    LicenseExtraction,
)
from app.eval.generator.hard_extraction_set import generate_hard_extraction_set
from app.eval.hard_extract_run import build_hard_extract_input, run_hard_extract


def _field(value: str | None, quote: str | None) -> ExtractedField:
    return ExtractedField(value=value, confidence=0.9, page=1, quote=quote)


def _manifest(tmp_path: Path) -> list[dict[str, Any]]:
    return generate_hard_extraction_set(tmp_path)


def test_build_hard_extract_input_reads_the_rendered_pdf(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    case = next(c for c in manifest if c["case_id"] == "noisy-1")
    extract_input = build_hard_extract_input(case, tmp_path)
    assert extract_input.kind == "license"
    assert "Janelle Castillo" in extract_input.document_text


def test_build_hard_extract_input_joins_all_pages(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    case = next(c for c in manifest if c["case_id"] == "multipage-1")
    extract_input = build_hard_extract_input(case, tmp_path)
    assert "Omar Haddad" in extract_input.document_text  # page 1
    assert "Issuing board" in extract_input.document_text  # page 2


class _CorrectExtractor:
    name = "claude"

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        if extract_input.kind == "license":
            return ExtractionResult(
                kind="license",
                fields=LicenseExtraction(
                    holder_name=_field("Janelle Castillo", "HOLDER - Janelle Castillo")
                ),
            )
        if extract_input.kind == "coi":
            return ExtractionResult(kind="coi", fields=CoiExtraction())
        return ExtractionResult(
            kind="cv",
            fields=CvExtraction(
                positions=[
                    CvPositionExtraction(
                        title=_field(
                            "Associate Counselor",
                            "Associate Counselor, Riverside Behavioral Health "
                            "(2019-02-01 to 2022-02-01)",
                        )
                    )
                ]
            ),
        )


def test_run_hard_extract_scores_a_correct_field(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    result = run_hard_extract(
        manifest, tmp_path, mode_name="hard-extract-test", backend=_CorrectExtractor()
    )
    noisy1 = next(d for d in result.documents if d.packet_id == "noisy-1")
    holder_name = next(f for f in noisy1.field_results if f.field == "license.holder_name")
    assert holder_name.correct is True


def test_run_hard_extract_covers_every_case(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    result = run_hard_extract(
        manifest, tmp_path, mode_name="hard-extract-test", backend=_CorrectExtractor()
    )
    assert len(result.documents) == len(manifest)


def test_run_hard_extract_scores_cv_positions(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    result = run_hard_extract(
        manifest, tmp_path, mode_name="hard-extract-test", backend=_CorrectExtractor()
    )
    cvformat1 = next(d for d in result.documents if d.packet_id == "cvformat-1")
    title_0 = next(f for f in cvformat1.field_results if f.field == "cv.positions[0].title")
    assert title_0.correct is True
    # cvformat-1 has 2 ground-truth positions; the stub only returned 1 -
    # position 1 is scored as a miss, not silently dropped.
    title_1 = next(f for f in cvformat1.field_results if f.field == "cv.positions[1].title")
    assert title_1.status == "unknown"


class _RaisingExtractor:
    name = "claude"

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        raise ValueError("Claude did not return a parsed structured output")


def test_run_hard_extract_handles_a_failure_without_crashing(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    result = run_hard_extract(
        manifest, tmp_path, mode_name="hard-extract-test", backend=_RaisingExtractor()
    )
    assert len(result.documents) == len(manifest)
    assert all(d.field_results == [] for d in result.documents)

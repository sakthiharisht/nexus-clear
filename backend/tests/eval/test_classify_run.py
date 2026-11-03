from __future__ import annotations

import json
from pathlib import Path

from app.backends.types import ClassificationResult, ClassifyInput
from app.eval.classify_run import _page1_text, build_classify_input, run_classify

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"


def _packet(packet_id: str) -> dict:
    return next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == packet_id)


class _StubBackend:
    name = "claude"

    def __init__(self) -> None:
        self.inputs: list[ClassifyInput] = []

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        self.inputs.append(classify_input)
        return ClassificationResult(
            doc_type="cv",
            probabilities={"cv": 0.9},
            legible=0.9,
            slot_match=True,
            decided_by="claude",
        )


def test_build_classify_input_extracts_real_page1_text_for_a_text_pdf() -> None:
    classify_input = build_classify_input(_packet("clean-1"), "license", FIXTURES_ROOT)
    assert classify_input.filename == "clean-1/license.pdf"
    assert "Christopher Lee" in classify_input.page1_text
    assert classify_input.page1_image_b64 is None


def test_build_classify_input_has_no_text_for_a_png_scan() -> None:
    classify_input = build_classify_input(
        _packet("benign-2-rotated-scan"), "license", FIXTURES_ROOT
    )
    assert classify_input.page1_text == ""
    # Deliberately no image attached here - see classify_run.py's
    # module docstring: image bytes aren't cross-platform reproducible
    # (this is exactly the D10/benign-2 scan that broke CI, seeded from
    # a different OS than the one that regenerates packets in CI).
    assert classify_input.page1_image_b64 is None


def test_filenames_differ_between_two_different_packets_scanned_license_slots() -> None:
    """Regression: benign-2-rotated-scan and defective-7 both render
    their license slot as license.png with no text layer, so their
    (slot, filename, page1_text) collided on the same cache key
    (app/backends/cache.py) when filename was just the bare basename -
    despite being genuinely different scans with very different
    ground-truth legibility. filename now includes the packet id."""
    a = build_classify_input(_packet("benign-2-rotated-scan"), "license", FIXTURES_ROOT)
    b = build_classify_input(_packet("defective-7"), "license", FIXTURES_ROOT)
    assert a.filename != b.filename


def test_run_classify_covers_every_uploaded_document_across_all_packets() -> None:
    backend = _StubBackend()
    result = run_classify(
        GROUND_TRUTH,
        FIXTURES_ROOT,
        mode_name="test-mode",
        primary=backend,
        fallback=None,
        tau_classify=0.85,
        legible_threshold=0.7,
    )
    # 12 packets x 5 slots, all uploaded in every packet.
    assert len(result.documents) == 60
    assert len(backend.inputs) == 60
    assert result.mode == "test-mode"


def test_run_classify_skips_a_slot_with_no_uploaded_document() -> None:
    fabricated_ground_truth = {
        "packets": [
            {
                "packet_id": "p1",
                "documents": {},  # nothing uploaded to any slot
                "facts": {
                    "documents": [
                        {
                            "slot": "license",
                            "expected_doc_type": "texas_lpc_license",
                            "uploaded_doc_type": None,
                            "legible_score": None,
                        }
                    ]
                },
            }
        ]
    }
    backend = _StubBackend()
    result = run_classify(
        fabricated_ground_truth,
        FIXTURES_ROOT,
        mode_name="test-mode",
        primary=backend,
        fallback=None,
        tau_classify=0.85,
        legible_threshold=0.7,
    )
    assert result.documents == []
    assert backend.inputs == []


def test_page1_text_returns_empty_for_a_corrupt_pdf(tmp_path: Path) -> None:
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"not a real pdf")
    assert _page1_text(bad_pdf) == ""


def test_run_classify_records_ground_truth_doc_types_for_the_wrong_doc_in_slot_defect() -> None:
    backend = _StubBackend()
    result = run_classify(
        GROUND_TRUTH,
        FIXTURES_ROOT,
        mode_name="test-mode",
        primary=backend,
        fallback=None,
        tau_classify=0.85,
        legible_threshold=0.7,
    )
    # defective-7 plants D09: the license slot actually contains a CV.
    license_doc = next(
        d for d in result.documents if d.packet_id == "defective-7" and d.slot == "license"
    )
    assert license_doc.expected_doc_type == "texas_lpc_license"
    assert license_doc.true_doc_type == "cv"

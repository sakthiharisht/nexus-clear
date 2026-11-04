"""M5.1 housekeeping #2: the hard classify set generator is
deterministic (same convention as test_determinism.py for the 12-
packet corpus), covers all five categories, and produces a manifest
app/eval/classify_run.py's existing build_classify_input/run_classify
can consume completely unchanged.
"""

from __future__ import annotations

from pathlib import Path

from app.backends.types import ClassificationResult, ClassifyInput
from app.eval.classify_run import build_classify_input, run_classify
from app.eval.generator.hard_classify_set import SEED, build_hard_cases, generate_hard_set


def test_generator_is_byte_identical_across_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"

    generate_hard_set(SEED, out_a)
    generate_hard_set(SEED, out_b)

    manifest_a = (out_a / "hard_classify_ground_truth.json").read_bytes()
    manifest_b = (out_b / "hard_classify_ground_truth.json").read_bytes()
    assert manifest_a == manifest_b

    rendered = sorted(p for p in (out_a / "hard").iterdir() if p.is_file())
    assert rendered, "generator produced no documents"
    diffs = [
        p.name for p in rendered if p.read_bytes() != (out_b / "hard" / p.name).read_bytes()
    ]
    assert diffs == []


def test_covers_all_five_categories() -> None:
    cases = build_hard_cases()
    categories = {c.category for c in cases}
    assert categories == {
        "lookalike",
        "cv_license_text",
        "degraded_scan",
        "mixed_content",
        "wrong_slot",
    }


def test_case_ids_are_unique() -> None:
    cases = build_hard_cases()
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))


def test_lookalikes_have_true_doc_type_other() -> None:
    cases = [c for c in build_hard_cases() if c.category == "lookalike"]
    assert cases
    assert all(c.true_doc_type == "other" for c in cases)


def test_wrong_slot_cases_have_expected_and_true_doc_type_differing() -> None:
    cases = [c for c in build_hard_cases() if c.category == "wrong_slot"]
    assert cases
    assert all(c.expected_doc_type != c.true_doc_type for c in cases)


def test_degraded_scans_are_low_legibility_ground_truth() -> None:
    cases = [c for c in build_hard_cases() if c.category == "degraded_scan"]
    assert cases
    assert all(c.legible_score < 0.5 for c in cases)


def test_manifest_shape_matches_the_main_corpus_so_run_classify_works_unchanged(
    tmp_path: Path,
) -> None:
    manifest = generate_hard_set(SEED, tmp_path)
    assert "packets" in manifest
    for packet in manifest["packets"]:
        assert set(packet["documents"].keys()) <= {"license", "coi", "cv", "education", "w9"}
        assert packet["facts"]["documents"][0]["slot"] in packet["documents"]


def test_build_classify_input_reads_real_rendered_text(tmp_path: Path) -> None:
    manifest = generate_hard_set(SEED, tmp_path)
    packet = next(p for p in manifest["packets"] if p["packet_id"] == "hard-lookalike-1099")
    classify_input = build_classify_input(packet, "w9", tmp_path)
    assert "1099" in classify_input.page1_text


class _StubBackend:
    name = "claude"
    prompt_version = "test"

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        return ClassificationResult(
            doc_type="other", probabilities={"other": 0.9}, legible=0.9, slot_match=True,
            decided_by="claude",
        )


def test_run_classify_covers_every_hard_case(tmp_path: Path) -> None:
    manifest = generate_hard_set(SEED, tmp_path)
    result = run_classify(
        manifest,
        tmp_path,
        mode_name="test-mode",
        primary=_StubBackend(),
        fallback=None,
        tau_classify=0.85,
        legible_threshold=0.7,
    )
    assert len(result.documents) == len(manifest["packets"])


def test_total_case_count_is_around_thirty() -> None:
    cases = build_hard_cases()
    assert 25 <= len(cases) <= 35

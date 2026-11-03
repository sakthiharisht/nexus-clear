"""Tests for app/eval/metrics.py's classification and aggregation logic,
using the real rule pack (for real rule kinds/field namespaces) with
hand-crafted PacketResult data to exercise each miss category precisely.
"""

from pathlib import Path

import pytest

from app.eval.metrics import compute_mode_metrics
from app.eval.types import ModeResult, PacketResult
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return load_rule_pack(REAL_PACK_PATH)


def _result(mode: str, packets: list[PacketResult]) -> ModeResult:
    return ModeResult(mode=mode, packets=packets)


def test_exact_match_rate_when_everything_matches(pack: RulePack) -> None:
    packet = PacketResult(
        packet_id="p1", kind="clean", defect_ids=[], actual={"R-LIC-001": "pass"},
        expected={"R-LIC-001": "pass"},
    )
    metrics = compute_mode_metrics(_result("ceiling", [packet]), pack)
    assert metrics.exact_match_rate == 1.0
    assert metrics.packet_exact_match == {"p1": True}
    assert metrics.misses == []


def test_per_rule_precision_recall(pack: RulePack) -> None:
    packets = [
        PacketResult(  # true positive
            packet_id="p1", kind="defective", defect_ids=["D01"],
            actual={"R-LIC-002": "fail"}, expected={"R-LIC-002": "fail"},
        ),
        PacketResult(  # false negative
            packet_id="p2", kind="defective", defect_ids=["D01"],
            actual={"R-LIC-002": "pass"}, expected={"R-LIC-002": "fail"},
        ),
        PacketResult(  # false positive
            packet_id="p3", kind="clean", defect_ids=[],
            actual={"R-LIC-002": "fail"}, expected={"R-LIC-002": "pass"},
        ),
        PacketResult(  # true negative
            packet_id="p4", kind="clean", defect_ids=[],
            actual={"R-LIC-002": "pass"}, expected={"R-LIC-002": "pass"},
        ),
    ]
    metrics = compute_mode_metrics(_result("baseline", packets), pack)
    r = metrics.per_rule["R-LIC-002"]
    assert (r.true_positive, r.false_positive, r.false_negative, r.true_negative) == (1, 1, 1, 1)
    assert r.precision == 0.5
    assert r.recall == 0.5


def test_false_positive_rate_only_counts_clean_and_benign_packets(pack: RulePack) -> None:
    packets = [
        PacketResult(
            packet_id="clean-1", kind="clean", defect_ids=[],
            actual={"R-LIC-001": "fail"}, expected={"R-LIC-001": "pass"},
        ),
        PacketResult(
            packet_id="defective-1", kind="defective", defect_ids=["D06"],
            actual={"R-LIC-001": "fail"}, expected={"R-LIC-001": "fail"},
        ),
    ]
    metrics = compute_mode_metrics(_result("baseline", packets), pack)
    assert metrics.false_positives_on_clean_or_benign == 1
    assert metrics.false_positive_rate_clean_benign == 1.0  # 1 of 1 clean/benign findings


def test_structural_no_reconcile_classification(pack: RulePack) -> None:
    packet = PacketResult(
        packet_id="p1", kind="clean", defect_ids=[],
        actual={"R-LIC-004": "unknown"}, expected={"R-LIC-004": "pass"},
    )
    metrics = compute_mode_metrics(_result("baseline", [packet]), pack)
    assert metrics.structural_miss_count == 1
    assert metrics.overlap_explained_miss_count == 0
    assert metrics.unexplained_miss_count == 0
    assert metrics.misses[0].category == "structural_no_reconcile"


def test_overlap_explained_classification(pack: RulePack) -> None:
    # Two defects (D09, D10) both target the "license" slot in this packet
    # -> any license-dependent finding that comes back unknown is
    # overlap-explained, not a standalone baseline gap.
    packet = PacketResult(
        packet_id="defective-7", kind="defective", defect_ids=["D09", "D10", "D14"],
        actual={"R-LIC-001": "unknown", "R-DOC-001:doc-license": "unknown"},
        expected={"R-LIC-001": "pass", "R-DOC-001:doc-license": "fail"},
    )
    metrics = compute_mode_metrics(_result("baseline", [packet]), pack)
    assert metrics.overlap_explained_miss_count == 2
    assert metrics.structural_miss_count == 0
    assert metrics.unexplained_miss_count == 0
    assert all(m.category == "overlap_explained" for m in metrics.misses)


def test_structural_no_ocr_classification_when_only_one_defect_on_the_slot(pack: RulePack) -> None:
    # Only D10 (not also D09) targets "license" here -> a single slot-
    # breaking defect is a plain "no OCR" structural gap, not an overlap.
    packet = PacketResult(
        packet_id="p1", kind="defective", defect_ids=["D10"],
        actual={"R-DOC-002:doc-license": "unknown"}, expected={"R-DOC-002:doc-license": "fail"},
    )
    metrics = compute_mode_metrics(_result("baseline", [packet]), pack)
    assert metrics.misses[0].category == "structural_no_ocr"


def test_unexplained_classification_for_an_unaccounted_mismatch(pack: RulePack) -> None:
    # A confidently-wrong answer (not "unknown") on an ordinary rule with
    # no structural or overlap cause -> genuinely unexplained.
    packet = PacketResult(
        packet_id="p1", kind="clean", defect_ids=[],
        actual={"R-WORK-001": "fail"}, expected={"R-WORK-001": "pass"},
    )
    metrics = compute_mode_metrics(_result("baseline", [packet]), pack)
    assert metrics.unexplained_miss_count == 1
    assert metrics.misses[0].category == "unexplained"


def test_per_defect_detected_uses_defect_overrides(pack: RulePack) -> None:
    packet = PacketResult(
        packet_id="p1", kind="defective", defect_ids=["D01"],
        actual={"R-LIC-002": "fail", "R-LIC-003": "not_applicable"},
        expected={"R-LIC-002": "fail", "R-LIC-003": "not_applicable"},
    )
    metrics = compute_mode_metrics(_result("ceiling", [packet]), pack)
    assert metrics.per_defect_detected == {"D01": True}
    assert metrics.primary_defect_detected_rate == 1.0


def test_unknown_rate(pack: RulePack) -> None:
    packet = PacketResult(
        packet_id="p1", kind="clean", defect_ids=[],
        actual={"R-LIC-001": "pass", "R-LIC-002": "unknown"},
        expected={"R-LIC-001": "pass", "R-LIC-002": "pass"},
    )
    metrics = compute_mode_metrics(_result("baseline", [packet]), pack)
    assert metrics.unknown_rate == 0.5

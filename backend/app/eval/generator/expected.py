"""Hand-authored expected Finding statuses per packet.

Deliberately independent of app.rules.engine: this is *my* understanding
of what each defect should do to which rule_id, written down before the
engine ever runs on this data. tests/eval/test_ground_truth.py runs the
real engine against each packet's CaseFacts and asserts it produces
exactly this — a real cross-check, not a tautological "record whatever
the engine says."
"""

from __future__ import annotations

from app.core.contracts import FindingStatus
from app.eval.generator.mutations import SLOTS

PER_DOCUMENT_RULE_IDS = ["R-DOC-001", "R-DOC-002", "R-SEC-001"]
SINGLE_RULE_IDS = [
    "R-LIC-001",
    "R-LIC-002",
    "R-LIC-003",
    "R-LIC-004",
    "R-SUP-001",
    "R-SUP-002",
    "R-COI-001",
    "R-COI-002",
    "R-COI-003",
    "R-COI-004",
    "R-WORK-001",
    "R-ID-001",
    "R-ID-002",
    "R-EXC-001",
    "R-PATH-001",
]

# Overrides applied on top of the clean baseline, one dict per defect.
# D06/D07 additionally flip R-SUP-001/002 off their not_applicable baseline
# (handled in `baseline_expected_findings`, driven by `is_associate`).
DEFECT_OVERRIDES: dict[str, dict[str, FindingStatus]] = {
    "D01": {"R-LIC-002": "fail", "R-LIC-003": "not_applicable"},
    "D02": {"R-LIC-003": "fail"},
    "D03": {"R-COI-001": "fail"},
    "D04": {"R-COI-002": "fail"},
    "D05": {"R-LIC-004": "fail", "R-ID-002": "fail"},
    "D06": {"R-LIC-001": "fail", "R-SUP-001": "pass", "R-SUP-002": "pass"},
    "D07": {"R-LIC-001": "fail", "R-SUP-001": "fail", "R-SUP-002": "pass"},
    "D08": {"R-WORK-001": "fail"},
    "D09": {"R-DOC-001:doc-license": "fail"},
    "D10": {"R-DOC-002:doc-license": "fail"},
    "D11": {"R-ID-002": "fail"},
    "D12": {"R-EXC-001": "unknown"},
    "D13": {"R-COI-004": "fail"},
    "D14": {"R-SEC-001:doc-cv": "fail"},
    "D15": {"R-ID-001": "fail"},
}


def baseline_expected_findings(is_associate: bool) -> dict[str, FindingStatus]:
    findings: dict[str, FindingStatus] = dict.fromkeys(SINGLE_RULE_IDS, "pass")
    if not is_associate:
        findings["R-SUP-001"] = "not_applicable"
        findings["R-SUP-002"] = "not_applicable"
    for rule_id in PER_DOCUMENT_RULE_IDS:
        for slot in SLOTS:
            findings[f"{rule_id}:doc-{slot}"] = "pass"
    return findings


def expected_findings(defect_ids: list[str]) -> dict[str, FindingStatus]:
    is_associate = any(d in {"D06", "D07"} for d in defect_ids)
    findings = baseline_expected_findings(is_associate)
    for defect_id in defect_ids:
        findings.update(DEFECT_OVERRIDES[defect_id])
    return findings

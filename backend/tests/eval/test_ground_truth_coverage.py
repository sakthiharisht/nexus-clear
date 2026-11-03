"""Coverage audit of the committed ground truth: every blocker-severity
rule must have at least one genuine positive among the defective packets
- either a confirmed `fail`, or (for a kind that structurally never fails,
like registry_exclusion_check's "escalate, don't auto-fail" design) an
`unknown` that represents a real finding requiring reviewer escalation,
not just an absence of data. A blocker rule that never fires anywhere in
the fixture set would be untested in exactly the place it matters most.
"""

import json
from pathlib import Path

import pytest

from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"
GROUND_TRUTH_PATH = REPO_ROOT / "eval" / "fixtures" / "ground_truth.json"

# Statuses that mean "this rule found nothing worth a human's attention" -
# anything else (fail, or unknown-as-escalation) is a genuine positive.
_INERT_STATUSES = {"pass", "not_applicable"}


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return load_rule_pack(REAL_PACK_PATH)


@pytest.fixture(scope="module")
def ground_truth() -> dict:
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


def _genuine_positives(ground_truth: dict, rule_id: str) -> list[tuple[str, str, str]]:
    positives = []
    for packet in ground_truth["packets"]:
        for finding_id, status in packet["expected_findings"].items():
            if finding_id.split(":", 1)[0] == rule_id and status not in _INERT_STATUSES:
                positives.append((packet["packet_id"], finding_id, status))
    return positives


def test_every_blocker_rule_has_a_genuine_positive(pack: RulePack, ground_truth: dict) -> None:
    blocker_rule_ids = [rule.id for rule in pack.rules if rule.severity == "blocker"]
    assert blocker_rule_ids, "expected at least one blocker rule in the pack"

    uncovered = [rid for rid in blocker_rule_ids if not _genuine_positives(ground_truth, rid)]
    assert uncovered == [], f"blocker rules with no genuine positive anywhere: {uncovered}"


def test_leie_possible_match_escalates_rather_than_auto_failing(
    pack: RulePack, ground_truth: dict
) -> None:
    """R-EXC-001 (registry_exclusion_check, blocker) can never resolve to
    `fail` by design (see app/rules/kinds.py:
    evaluate_registry_exclusion_check) - a possible match must go to a
    human reviewer, not be auto-decided either way. D12's packet is this
    pack's one genuine positive for R-EXC-001; assert it's shaped exactly
    the way an escalation-worthy blocker finding should be.
    """
    exc_rule = next(r for r in pack.rules if r.id == "R-EXC-001")
    assert exc_rule.severity == "blocker"
    assert exc_rule.kind == "registry_exclusion_check"

    positives = _genuine_positives(ground_truth, "R-EXC-001")
    assert positives, "expected at least one LEIE possible-match packet in ground truth"
    packet_id, finding_id, status = positives[0]
    assert status == "unknown"

    packet = next(p for p in ground_truth["packets"] if p["packet_id"] == packet_id)
    assert "D12" in packet["defect_ids"]
    leie_result = packet["facts"]["registry_results"].get("R-EXC-001")
    assert leie_result is not None
    assert leie_result["possible_match"] is True

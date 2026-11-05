"""Boundary tests for app/escalate/engine.py's five escalation
criteria, using the real rule pack (for real kinds/severities) with
hand-crafted Finding data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.contracts import EvidenceRef, Finding, RuleSource
from app.escalate.engine import EscalationDecision, EscalationThresholds, escalate
from app.rules.loader import load_rule_pack
from app.rules.schema import Rule, RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"

_THRESHOLDS = EscalationThresholds(low_confidence_threshold=0.60, blocker_confidence_threshold=0.90)
_SOURCE = RuleSource(source_id="s", last_verified="2026-01-01", needs_verification=False)


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return load_rule_pack(REAL_PACK_PATH)


def _rules_by_id(pack: RulePack) -> dict[str, Rule]:
    return {rule.id: rule for rule in pack.rules}


def _finding(
    rule_id: str,
    *,
    status: str = "pass",
    severity: str = "blocker",
    confidence: float | None = None,
) -> Finding:
    return Finding(
        finding_id=rule_id,
        rule_id=rule_id,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        evidence=[EvidenceRef(kind="document")],
        rule_source=_SOURCE,
        confidence=confidence,
        decided_by="code",
    )


def _escalate(
    pack: RulePack,
    findings: list[Finding],
    unverified: set[str] | None = None,
    has_gap_explanation: bool = False,
) -> list[EscalationDecision]:
    return escalate(
        findings,
        rules_by_id=_rules_by_id(pack),
        unverified_namespaces=unverified or set(),
        thresholds=_THRESHOLDS,
        has_gap_explanation=has_gap_explanation,
    )


def test_a_clean_finding_never_escalates(pack: RulePack) -> None:
    # R-LIC-002: blocker, date_not_expired, no confidence at all (pure
    # code decision) - nothing here should trigger any of the five
    # criteria.
    decisions = _escalate(pack, [_finding("R-LIC-002", status="pass", severity="blocker")])
    assert decisions[0].reasons == []
    assert decisions[0].escalated is False


def test_low_confidence_escalates_regardless_of_severity(pack: RulePack) -> None:
    # R-COI-004 is warning severity - the generic low-confidence rule
    # must still catch it.
    decisions = _escalate(
        pack, [_finding("R-COI-004", severity="warning", confidence=0.59)]
    )
    assert decisions[0].reasons == ["low_confidence"]


def test_low_confidence_boundary_at_threshold_does_not_escalate(pack: RulePack) -> None:
    decisions = _escalate(
        pack, [_finding("R-COI-004", severity="warning", confidence=0.60)]
    )
    assert decisions[0].reasons == []


def test_blocker_override_escalates_in_the_0_60_to_0_90_band(pack: RulePack) -> None:
    # R-LIC-004 is blocker severity - 0.75 clears the general 0.60 bar
    # but not the blocker-specific 0.90 bar.
    decisions = _escalate(pack, [_finding("R-LIC-004", severity="blocker", confidence=0.75)])
    assert decisions[0].reasons == ["blocker_low_confidence"]


def test_blocker_override_boundary_at_threshold_does_not_escalate(pack: RulePack) -> None:
    decisions = _escalate(pack, [_finding("R-LIC-004", severity="blocker", confidence=0.90)])
    assert decisions[0].reasons == []


def test_blocker_below_both_thresholds_reports_both_reasons(pack: RulePack) -> None:
    decisions = _escalate(pack, [_finding("R-LIC-004", severity="blocker", confidence=0.50)])
    assert set(decisions[0].reasons) == {"low_confidence", "blocker_low_confidence"}


def test_leie_possible_match_escalates_with_no_confidence_at_all(pack: RulePack) -> None:
    decisions = _escalate(
        pack, [_finding("R-EXC-001", status="unknown", severity="blocker", confidence=None)]
    )
    assert decisions[0].reasons == ["leie_possible_match"]


def test_leie_pass_does_not_escalate(pack: RulePack) -> None:
    decisions = _escalate(pack, [_finding("R-EXC-001", status="pass", severity="blocker")])
    assert decisions[0].reasons == []


def test_unverified_quote_on_blocker_escalates_when_namespace_matches(pack: RulePack) -> None:
    # R-LIC-002's field is license.expiration_date -> namespace "license".
    decisions = _escalate(
        pack, [_finding("R-LIC-002", severity="blocker")], unverified={"license"}
    )
    assert decisions[0].reasons == ["unverified_quote_on_blocker"]


def test_unverified_quote_does_not_escalate_a_different_namespace(pack: RulePack) -> None:
    decisions = _escalate(
        pack, [_finding("R-LIC-002", severity="blocker")], unverified={"coi"}
    )
    assert decisions[0].reasons == []


def test_unverified_quote_on_a_warning_rule_does_not_escalate(pack: RulePack) -> None:
    # R-DOC-002 (legibility, warning) touches no CaseFacts namespace at
    # all (per-document kind) - and isn't a blocker regardless.
    decisions = _escalate(
        pack, [_finding("R-DOC-002", severity="warning")], unverified={"license"}
    )
    assert decisions[0].reasons == []


def test_injection_flag_escalates_on_fail_despite_info_severity(pack: RulePack) -> None:
    decisions = _escalate(pack, [_finding("R-SEC-001", status="fail", severity="info")])
    assert decisions[0].reasons == ["injection_flag"]


def test_injection_flag_pass_does_not_escalate(pack: RulePack) -> None:
    decisions = _escalate(pack, [_finding("R-SEC-001", status="pass", severity="info")])
    assert decisions[0].reasons == []


def test_gap_explanation_escalates_a_failing_history_gap_finding(pack: RulePack) -> None:
    decisions = _escalate(
        pack,
        [_finding("R-WORK-001", status="fail", severity="warning")],
        has_gap_explanation=True,
    )
    assert decisions[0].reasons == ["gap_explanation_provided"]


def test_no_gap_explanation_does_not_escalate_a_failing_history_gap_finding(
    pack: RulePack,
) -> None:
    # Current behavior, unchanged: without an explanation on file, a
    # confidence-less warning-severity fail has no other criterion to
    # trigger on.
    decisions = _escalate(
        pack,
        [_finding("R-WORK-001", status="fail", severity="warning")],
        has_gap_explanation=False,
    )
    assert decisions[0].reasons == []


def test_gap_explanation_on_a_passing_history_gap_finding_does_not_escalate(
    pack: RulePack,
) -> None:
    # Providing an explanation never flips a finding to escalate unless
    # code already decided "fail" - a resolved gap stays resolved.
    decisions = _escalate(
        pack,
        [_finding("R-WORK-001", status="pass", severity="warning")],
        has_gap_explanation=True,
    )
    assert decisions[0].reasons == []


def test_a_finding_for_an_unknown_rule_id_does_not_crash(pack: RulePack) -> None:
    # Defensive: rules_by_id.get() returns None for a rule_id not in
    # the pack - every kind-specific check must short-circuit cleanly.
    decisions = escalate(
        [_finding("R-NOT-REAL", severity="blocker")],
        rules_by_id=_rules_by_id(pack),
        unverified_namespaces={"license"},
        thresholds=_THRESHOLDS,
    )
    assert decisions[0].reasons == []

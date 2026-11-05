"""Escalate eval (SPEC.md section 7.7, M8): runs the real pipeline
(Extract -> Reconcile -> Validate, the same stages app/eval/end_to_end_run.py
scores) over the 15-packet ground truth, escalates every resulting
Finding (app/escalate/engine.py), and reports the escalation rate plus
precision/recall against this corpus's own known escalation-relevant
defects.

Reuses app/eval/end_to_end_run.py's `_extract_case_facts` directly
rather than its `run_end_to_end` wrapper: that wrapper's own
PacketResult/ModeResult types only carry a finding_id -> status dict
(app/eval/types.py) for the M3 report's miss-explanation machinery -
not enough to escalate with, since escalate() needs each Finding's
confidence, severity, and rule_source too.

Ground truth, scoped honestly - five (packet_id, finding_id) pairs in
this corpus have a defect whose escalation outcome is knowable ahead
of time -
- defective-3's D13 (COI insured name is a different practice
  entirely): R-COI-004 resolves to a confident "fail" in the end, but
  getting there needs the Investigator (a genuine mismatch, not an
  exact string match) - low_confidence.
- defective-4's D11 (license holder name is an unrelated stranger's):
  R-LIC-004, same reason - low_confidence and blocker_low_confidence
  (R-LIC-004 is a blocker; R-COI-004 above is only a warning).
- defective-8's D12 (a synthetic LEIE possible-match): R-EXC-001
  should escalate (leie_possible_match).
- defective-7's D14 (an injected-instruction CV): R-SEC-001 should
  escalate (injection_flag).
- benign-4-middle-initial (pre-M9 fix #5: "Robert Chen" vs "Robert J.
  Chen"): a real person, but the live Investigator's resolved
  confidence (0.88, checked directly) lands just under
  blocker_confidence_threshold (0.90) - blocker_low_confidence,
  verified empirically, not assumed. The other two pre-M9 fix #5
  packets (a hyphenated surname, a generational suffix) resolved
  confidently (0.95, 0.90) and do NOT escalate - a real, not
  engineered, split result across three name variants that look
  equally "ambiguous" on paper.
Every other finding in this corpus resolves exactly (a clean name
match, confidence 1.0, resolved in code with no model call at all -
app/reconcile/engine.py) and is expected to never escalate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backends.extract_cache import ExtractionBackend
from app.core.contracts import Finding
from app.escalate.engine import EscalationThresholds, escalate
from app.eval.end_to_end_run import _extract_case_facts
from app.reconcile.engine import reconcile
from app.reconcile.investigator import InvestigatorLike
from app.rules.engine import evaluate_rule_pack
from app.rules.schema import RulePack

GROUND_TRUTH_ESCALATIONS: dict[tuple[str, str], bool] = {
    ("defective-3", "R-COI-004"): True,
    ("defective-4", "R-LIC-004"): True,
    ("defective-8", "R-EXC-001"): True,
    # R-SEC-001 (injection_flag) is a per-document kind, evaluated once
    # per uploaded document in the packet - keyed on the exact
    # finding_id (rule_id:doc_id, app/rules/engine.py's convention), not
    # the bare rule_id, so the other four documents in this same packet
    # (license/coi/education/w9, which correctly never flag) don't each
    # count as a false negative against the one that should.
    ("defective-7", "R-SEC-001:doc-cv"): True,
    ("benign-4-middle-initial", "R-LIC-004"): True,
}


class EscalationEvalResult(BaseModel):
    mode: str
    total_findings: int
    escalated_count: int
    escalation_rate: float
    # None when no ground-truth-labeled finding showed up in this run
    # at all - nothing to score, not a 0/0 coerced into a number.
    precision: float | None
    recall: float | None
    true_positives: int
    false_positives: int
    false_negatives: int
    simulated: bool = False


def run_escalate_eval(
    pack: RulePack,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    *,
    mode_name: str,
    extractor: ExtractionBackend,
    investigator: InvestigatorLike,
    thresholds: EscalationThresholds,
) -> EscalationEvalResult:
    rules_by_id = {rule.id: rule for rule in pack.rules}

    total = 0
    escalated_count = 0
    true_positives = false_positives = false_negatives = 0
    simulated = False

    for packet in ground_truth["packets"]:
        facts, _notes, packet_simulated = _extract_case_facts(packet, fixtures_root, extractor)
        simulated = simulated or packet_simulated
        facts = reconcile(pack, facts, investigator=investigator)
        findings: list[Finding] = evaluate_rule_pack(pack, facts, facts.target_date)

        unverified_namespaces: set[str] = set()  # not tracked by this eval path
        decisions = escalate(
            findings,
            rules_by_id=rules_by_id,
            unverified_namespaces=unverified_namespaces,
            thresholds=thresholds,
        )

        for decision in decisions:
            total += 1
            if decision.escalated:
                escalated_count += 1

            expected = GROUND_TRUTH_ESCALATIONS.get((packet["packet_id"], decision.finding_id))
            if expected is None:
                continue
            if expected and decision.escalated:
                true_positives += 1
            elif expected and not decision.escalated:
                false_negatives += 1
            elif not expected and decision.escalated:
                false_positives += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else None
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else None
    )
    final_mode = f"{mode_name}-SIMULATED" if simulated else mode_name

    return EscalationEvalResult(
        mode=final_mode,
        total_findings=total,
        escalated_count=escalated_count,
        escalation_rate=escalated_count / total if total else 0.0,
        precision=precision,
        recall=recall,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        simulated=simulated,
    )

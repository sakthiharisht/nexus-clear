"""Metrics for the M3 eval runner (SPEC.md section 14).

Every finding mismatch is sorted into one of four buckets, not lumped
together as "failures". Document readability is checked first, even for
name_match/registry_* rules — R-LIC-004 depends on license.holder_name
the same way R-LIC-002 depends on license.expiration_date, so an
unreadable license document explains *both* misses the same way, not
"no OCR" for one and "no Reconcile" for the other:
  overlap_explained       - the rule depends on a document slot that's
      unreadable *because* another defect in this same packet degraded
      it (e.g. D10 renders the slot D09 misfiled as an illegible scan) -
      a defect-interaction, not a standalone baseline gap.
  structural_no_ocr       - the rule depends on a document slot baseline
      couldn't read at all, with no second defect to blame (a scanned/
      image document; no OCR capability).
  structural_no_reconcile - the rule is name_match/registry_* and the
      *document* side was readable fine, but baseline reconcile
      (app/eval/baseline_reconcile.py) still couldn't resolve it - an
      ambiguous fuzzy name score, or no matching registry fixture entry.
  unexplained             - anything left over: a real, unaccounted-for
      miss worth investigating (this would also catch a *wrong* decided
      answer from baseline reconcile, not just a missing one - the
      thresholds in baseline_reconcile.py are chosen to avoid that, but
      if it ever happens this is where it would show up).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from pydantic import BaseModel

from app.core.contracts import FindingStatus
from app.eval.generator.expected import DEFECT_OVERRIDES
from app.eval.types import ModeResult, PacketResult
from app.rules.schema import Rule, RulePack

STRUCTURAL_KINDS = {
    "name_match",
    "registry_status_check",
    "registry_flags_check",
    "registry_exclusion_check",
}

# Defects that render one specific document slot unreadable or
# misclassified. Used to detect when one defect's finding is undetectable
# only because another defect broke extraction on the same slot.
DEFECT_SLOTS: dict[str, str] = {
    "D09": "license",
    "D10": "license",
    "D14": "cv",
}


class RuleMetrics(BaseModel):
    rule_id: str
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0

    @property
    def precision(self) -> float | None:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else None


class MissExplanation(BaseModel):
    packet_id: str
    finding_id: str
    expected: FindingStatus
    actual: FindingStatus | None
    category: str
    explanation: str


class ModeMetrics(BaseModel):
    mode: str
    per_rule: dict[str, RuleMetrics]
    packet_exact_match: dict[str, bool]
    exact_match_rate: float
    primary_defect_detected_rate: float
    false_positives_on_clean_or_benign: int
    false_positive_rate_clean_benign: float
    unknown_rate: float
    # Share of findings where the ground truth itself has a decidable
    # answer (expected != "unknown") that baseline actually decided
    # (didn't fall back to unknown). Excludes findings ground truth itself
    # can't decide (e.g. D12's LEIE possible-match -> unknown + escalate)
    # - matching that with unknown is success, not a coverage gap.
    coverage: float
    # Of the findings baseline *did* decide (actual != "unknown"), the
    # share that matched expected. Complements coverage: coverage asks
    # "how often does baseline commit to an answer", this asks "when it
    # does, how often is it right" - the number that should stay high even
    # as coverage improves, per "never guess".
    accuracy_when_decided: float
    per_defect_detected: dict[str, bool]
    misses: list[MissExplanation]
    structural_miss_count: int
    overlap_explained_miss_count: int
    unexplained_miss_count: int


def rule_namespace_map(pack: RulePack) -> dict[str, str]:
    """rule_id -> the CaseFacts namespace ("license"/"coi"/"cv"/...) its
    first field reference points into, for rules with a single-value kind
    (per-document kinds carry their slot in the finding_id itself)."""
    namespaces: dict[str, str] = {}
    for rule in pack.rules:
        ns = _rule_namespace(rule)
        if ns is not None:
            namespaces[rule.id] = ns
    return namespaces


def _rule_namespace(rule: Rule) -> str | None:
    params = rule.parsed_params()
    field = getattr(params, "field", None) or getattr(params, "left", None)
    if field is None:
        fields = getattr(params, "fields", None)
        field = fields[0] if fields else None
    if field is None:
        return None
    return str(field).split(".", 1)[0]


def _affected_slot(finding_id: str, rule_id: str, rule_namespaces: dict[str, str]) -> str | None:
    if ":doc-" in finding_id:
        return finding_id.split(":doc-", 1)[1]
    namespace = rule_namespaces.get(rule_id)
    return namespace if namespace in ("license", "coi", "cv") else None


def _slot_extraction_gap(packet: PacketResult, slot: str) -> str | None:
    """Evidence-based, not inferred: a reason code only when some stage
    actually recorded this slot as never reaching real extracted values
    (extraction_notes), never just because some finding touching it came
    back unknown - an unknown name_match score, for instance, doesn't
    mean the document was unreadable, just that reconcile couldn't commit
    to an answer. None when no note explains the gap.

    "no_ocr": no extractable text layer / no document uploaded
        (app/eval/baseline_extraction.py, app/eval/end_to_end_run.py).
    "wrong_doc_type": the real upload doesn't match this slot's schema
        (app/eval/end_to_end_run.py - a D09-style wrong document in slot).
    "extraction_failed": the extractor raised and was recorded as a note
        instead of a crash (app/eval/end_to_end_run.py).
    """
    prefix = f"{slot}:"
    for note in packet.extraction_notes:
        if not note.startswith(prefix):
            continue
        if "no extractable text layer" in note or "no document uploaded" in note:
            return "no_ocr"
        if "doesn't match this schema" in note:
            return "wrong_doc_type"
        if "extraction failed" in note:
            return "extraction_failed"
    return None


def _classify_miss(
    packet: PacketResult,
    finding_id: str,
    expected: FindingStatus,
    actual: FindingStatus | None,
    rule_kinds: Mapping[str, str],
    rule_namespaces: dict[str, str],
    slot_defect_counts: dict[tuple[str, str], int],
) -> MissExplanation:
    rule_id = finding_id.split(":", 1)[0]
    kind = rule_kinds.get(rule_id)

    # Document-readability first, even for name_match/registry_* kinds:
    # R-LIC-004 depends on license.holder_name same as R-LIC-001/002/003
    # do (via `left`, not `field`, but _rule_namespace handles both) - if
    # the license document itself is unreadable, that's *why* R-LIC-004
    # can't be decided, not a generic "no Reconcile stage" gap. Only fall
    # back to the blanket structural_no_reconcile explanation below when
    # there's no document-readability story to tell (the slot was fine;
    # reconcile just didn't have enough signal, e.g. an ambiguous fuzzy
    # name score, or a registry fixture with no matching entry).
    slot = _affected_slot(finding_id, rule_id, rule_namespaces)
    gap = (
        _slot_extraction_gap(packet, slot)
        if actual == "unknown" and slot is not None
        else None
    )
    if gap is not None and slot is not None:
        count = slot_defect_counts.get((packet.packet_id, slot), 0)
        if count >= 2:
            other = [d for d in packet.defect_ids if DEFECT_SLOTS.get(d) == slot]
            return MissExplanation(
                packet_id=packet.packet_id,
                finding_id=finding_id,
                expected=expected,
                actual=actual,
                category="overlap_explained",
                explanation=(
                    f"{slot} document is unreadable because of {', '.join(other)} "
                    "co-occurring on the same slot in this packet"
                ),
            )
        if gap == "wrong_doc_type":
            return MissExplanation(
                packet_id=packet.packet_id,
                finding_id=finding_id,
                expected=expected,
                actual=actual,
                category="structural_wrong_doc_type",
                explanation=(
                    f"{slot} document is a different document type than this rule's "
                    "extraction expects - the real upload doesn't match the slot's "
                    "schema, so there is nothing to extract"
                ),
            )
        if gap == "extraction_failed":
            return MissExplanation(
                packet_id=packet.packet_id,
                finding_id=finding_id,
                expected=expected,
                actual=actual,
                category="structural_extraction_failed",
                explanation=f"{slot} extraction raised an error and was left unknown, not guessed",
            )
        return MissExplanation(
            packet_id=packet.packet_id,
            finding_id=finding_id,
            expected=expected,
            actual=actual,
            category="structural_no_ocr",
            explanation=(
                f"{slot} document has no extractable text layer (scanned image); "
                "this eval path has no OCR/vision capability for it"
            ),
        )

    if kind in STRUCTURAL_KINDS:
        return MissExplanation(
            packet_id=packet.packet_id,
            finding_id=finding_id,
            expected=expected,
            actual=actual,
            category="structural_no_reconcile",
            explanation=(
                f"{rule_id} is a {kind} rule baseline reconcile couldn't resolve "
                "(ambiguous fuzzy match or no matching registry fixture entry) - "
                "not a document-readability problem"
            ),
        )

    return MissExplanation(
        packet_id=packet.packet_id,
        finding_id=finding_id,
        expected=expected,
        actual=actual,
        category="unexplained",
        explanation="no known structural or overlap explanation",
    )


def compute_mode_metrics(result: ModeResult, pack: RulePack) -> ModeMetrics:
    rule_kinds = {rule.id: rule.kind for rule in pack.rules}
    rule_namespaces = rule_namespace_map(pack)

    slot_defect_counts: dict[tuple[str, str], int] = defaultdict(int)
    for packet in result.packets:
        for defect_id in packet.defect_ids:
            slot = DEFECT_SLOTS.get(defect_id)
            if slot:
                slot_defect_counts[(packet.packet_id, slot)] += 1

    per_rule: dict[str, RuleMetrics] = {}
    packet_exact_match: dict[str, bool] = {}
    misses: list[MissExplanation] = []
    total_findings = 0
    unknown_findings = 0
    fp_clean_benign = 0
    total_clean_benign_findings = 0
    decidable_findings = 0  # expected != "unknown"
    decidable_and_decided = 0  # expected != "unknown" and actual != "unknown"
    decided_findings = 0  # actual != "unknown"
    decided_and_correct = 0  # actual != "unknown" and actual == expected

    for packet in result.packets:
        exact = True
        for finding_id, expected_status in packet.expected.items():
            actual_status = packet.actual.get(finding_id)
            total_findings += 1
            if actual_status == "unknown":
                unknown_findings += 1

            if expected_status != "unknown":
                decidable_findings += 1
                if actual_status != "unknown":
                    decidable_and_decided += 1
            if actual_status is not None and actual_status != "unknown":
                decided_findings += 1
                if actual_status == expected_status:
                    decided_and_correct += 1

            rule_id = finding_id.split(":", 1)[0]
            metrics = per_rule.setdefault(rule_id, RuleMetrics(rule_id=rule_id))

            expected_positive = expected_status == "fail"
            actual_positive = actual_status == "fail"
            if expected_positive and actual_positive:
                metrics.true_positive += 1
            elif expected_positive and not actual_positive:
                metrics.false_negative += 1
            elif not expected_positive and actual_positive:
                metrics.false_positive += 1
            else:
                metrics.true_negative += 1

            if packet.kind in ("clean", "benign"):
                total_clean_benign_findings += 1
                if actual_positive and not expected_positive:
                    fp_clean_benign += 1

            if actual_status != expected_status:
                exact = False
                misses.append(
                    _classify_miss(
                        packet,
                        finding_id,
                        expected_status,
                        actual_status,
                        rule_kinds,
                        rule_namespaces,
                        slot_defect_counts,
                    )
                )

        packet_exact_match[packet.packet_id] = exact

    defective_packets = [p for p in result.packets if p.defect_ids]
    primary_detected = 0
    per_defect_detected: dict[str, bool] = {}
    for packet in defective_packets:
        primary_overrides = DEFECT_OVERRIDES[packet.defect_ids[0]]
        if all(packet.actual.get(fid) == status for fid, status in primary_overrides.items()):
            primary_detected += 1
        for defect_id in packet.defect_ids:
            overrides = DEFECT_OVERRIDES[defect_id]
            per_defect_detected[defect_id] = all(
                packet.actual.get(fid) == status for fid, status in overrides.items()
            )

    return ModeMetrics(
        mode=result.mode,
        per_rule=per_rule,
        packet_exact_match=packet_exact_match,
        exact_match_rate=(
            sum(packet_exact_match.values()) / len(packet_exact_match)
            if packet_exact_match
            else 1.0
        ),
        primary_defect_detected_rate=(
            primary_detected / len(defective_packets) if defective_packets else 1.0
        ),
        false_positives_on_clean_or_benign=fp_clean_benign,
        false_positive_rate_clean_benign=(
            fp_clean_benign / total_clean_benign_findings if total_clean_benign_findings else 0.0
        ),
        unknown_rate=(unknown_findings / total_findings if total_findings else 0.0),
        coverage=(
            decidable_and_decided / decidable_findings if decidable_findings else 1.0
        ),
        accuracy_when_decided=(
            decided_and_correct / decided_findings if decided_findings else 1.0
        ),
        per_defect_detected=per_defect_detected,
        misses=misses,
        structural_miss_count=sum(1 for m in misses if m.category.startswith("structural")),
        overlap_explained_miss_count=sum(1 for m in misses if m.category == "overlap_explained"),
        unexplained_miss_count=sum(1 for m in misses if m.category == "unexplained"),
    )

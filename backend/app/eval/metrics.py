"""Metrics for the M3 eval runner (SPEC.md section 14).

Every finding mismatch is sorted into one of three buckets, not lumped
together as "failures":
  structural_no_reconcile - the rule is name_match/registry_* and baseline
      has no Reconcile stage or MCP tools yet to resolve it (true at
      every packet, not specific to this one).
  structural_no_ocr       - the rule depends on a document slot baseline
      couldn't read at all (a scanned/image document; no OCR capability).
  overlap_explained       - same as structural_no_ocr, but the slot is
      unreadable *because* another defect in this same packet degraded
      it (e.g. D10 renders the slot D09 misfiled as an illegible scan) -
      a defect-interaction, not a standalone baseline gap.
  unexplained             - anything left over: a real, unaccounted-for
      miss worth investigating.
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

    if kind in STRUCTURAL_KINDS:
        return MissExplanation(
            packet_id=packet.packet_id,
            finding_id=finding_id,
            expected=expected,
            actual=actual,
            category="structural_no_reconcile",
            explanation=(
                f"{rule_id} is a {kind} rule; baseline has no Reconcile stage "
                "or MCP tools yet to resolve it"
            ),
        )

    slot = _affected_slot(finding_id, rule_id, rule_namespaces)
    if actual == "unknown" and slot is not None:
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
        return MissExplanation(
            packet_id=packet.packet_id,
            finding_id=finding_id,
            expected=expected,
            actual=actual,
            category="structural_no_ocr",
            explanation=(
                f"{slot} document has no extractable text layer (scanned image); "
                "baseline has no OCR/vision capability"
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

    for packet in result.packets:
        exact = True
        for finding_id, expected_status in packet.expected.items():
            actual_status = packet.actual.get(finding_id)
            total_findings += 1
            if actual_status == "unknown":
                unknown_findings += 1

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
        per_defect_detected=per_defect_detected,
        misses=misses,
        structural_miss_count=sum(1 for m in misses if m.category.startswith("structural")),
        overlap_explained_miss_count=sum(1 for m in misses if m.category == "overlap_explained"),
        unexplained_miss_count=sum(1 for m in misses if m.category == "unexplained"),
    )

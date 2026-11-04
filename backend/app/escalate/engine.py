"""Escalate (SPEC.md section 7.7): routes uncertain or risky Findings
to the reviewer queue instead of letting them resolve silently.
Thresholds are configurable (app/core/config.py) and the whole engine
is pure - findings in, decisions out, no DB/model calls here (those
happen at the orchestrator, which persists the resulting ReviewItem
rows for whatever this reports as escalated).

Five independent criteria, any one of which escalates a finding:
1. low_confidence: a resolved confidence below low_confidence_threshold,
   regardless of severity - SPEC 7.7's default "<0.60 -> review".
2. blocker_low_confidence: a blocker whose confidence is below
   blocker_confidence_threshold even if it clears (1) - SPEC 7.7's
   severity override ("any blocker with confidence < 0.90 goes to
   review").
3. leie_possible_match: a registry_exclusion_check finding reporting
   `unknown` - this kind's own docstring (app/rules/kinds.py) already
   documents that a possible match can't be auto-resolved; it always
   needs a human, with no confidence score to threshold against.
4. unverified_quote_on_blocker: a blocker whose CaseFacts namespace
   (license/coi/cv) contains at least one field the extractor returned
   with a `known` status but an unverified quote (an image document
   with no text layer to check against, app/core/citations.py) - the
   model's own say-so fed a high-stakes rule with no code-side check.
5. injection_flag: an injection_flag finding reporting `fail` - CLAUDE.md
   invariant 3 territory, always reviewed regardless of its "info"
   severity, since a detected injection attempt is never routine.

Name-match ambiguity (listed in the M8 brief alongside these) isn't a
separate code path: name_match is exactly the kind whose `confidence`
is the Investigator's resolved match probability, so an ambiguous
match surfaces through (1)/(2) above on its own merits, scored the
same as every other uncertain finding - a separate special case would
just be a second way of saying the same threshold check.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.core.contracts import Finding
from app.rules.schema import Rule

EscalationReason = Literal[
    "low_confidence",
    "blocker_low_confidence",
    "leie_possible_match",
    "unverified_quote_on_blocker",
    "injection_flag",
]


class EscalationThresholds(BaseModel):
    low_confidence_threshold: float
    blocker_confidence_threshold: float


class EscalationDecision(BaseModel):
    finding_id: str
    rule_id: str
    reasons: list[EscalationReason] = []

    @property
    def escalated(self) -> bool:
        return bool(self.reasons)


def _rule_namespace(rule: Rule) -> str | None:
    """The CaseFacts namespace ("license"/"coi"/"cv"/...) this rule's
    first field reference points into - mirrors app/eval/metrics.py's
    helper of the same name and shape, kept as an independent copy
    since app/escalate (shipped, production code) must not depend on
    app/eval (a test/dev-only package)."""
    params = rule.parsed_params()
    field = getattr(params, "field", None) or getattr(params, "left", None)
    if field is None:
        fields = getattr(params, "fields", None)
        field = fields[0] if fields else None
    if field is None:
        return None
    return str(field).split(".", 1)[0]


def escalate(
    findings: list[Finding],
    *,
    rules_by_id: dict[str, Rule],
    unverified_namespaces: set[str],
    thresholds: EscalationThresholds,
) -> list[EscalationDecision]:
    decisions: list[EscalationDecision] = []
    for finding in findings:
        reasons: list[EscalationReason] = []
        rule = rules_by_id.get(finding.rule_id)

        if finding.confidence is not None:
            if finding.confidence < thresholds.low_confidence_threshold:
                reasons.append("low_confidence")
            if (
                finding.severity == "blocker"
                and finding.confidence < thresholds.blocker_confidence_threshold
            ):
                reasons.append("blocker_low_confidence")

        if (
            rule is not None
            and rule.kind == "registry_exclusion_check"
            and finding.status == "unknown"
        ):
            reasons.append("leie_possible_match")

        if (
            rule is not None
            and finding.severity == "blocker"
            and _rule_namespace(rule) in unverified_namespaces
        ):
            reasons.append("unverified_quote_on_blocker")

        if rule is not None and rule.kind == "injection_flag" and finding.status == "fail":
            reasons.append("injection_flag")

        decisions.append(
            EscalationDecision(
                finding_id=finding.finding_id, rule_id=finding.rule_id, reasons=reasons
            )
        )
    return decisions

"""The Validate stage (SPEC.md section 7.4): evaluate every rule in a
RulePack against CaseFacts and emit Findings.

Pure and deterministic — no network, no `now()` (`as_of` is an explicit
argument). `applies_when` gating happens here, uniformly, before any
kind-specific logic runs, so a gated-out rule is always `not_applicable`
and never reaches a kind evaluator that doesn't apply to it. The three
per-document kinds (doc_type_match, legibility, injection_flag) are
dispatched once per uploaded document, producing one Finding per document
rather than one Finding per rule — see app/rules/context.py's DocumentFact
docstring for why.
"""

from datetime import date

from app.core.contracts import EvidenceRef, Finding, RuleSource
from app.rules import kinds
from app.rules.context import CaseFacts, DocumentFact, get_path
from app.rules.kinds import EvalContext, KindResult
from app.rules.schema import (
    ChecksumParams,
    DateExpiringSoonParams,
    DateNotExpiredParams,
    DocTypeMatchParams,
    EnumMatchParams,
    HistoryGapParams,
    InjectionFlagParams,
    LegibilityParams,
    NameMatchParams,
    NumericMaxParams,
    NumericMinPairParams,
    PathRouteParams,
    PresenceAllParams,
    RegistryCheckParams,
    Rule,
    RulePack,
)

_PER_DOCUMENT_KINDS = frozenset({"doc_type_match", "legibility", "injection_flag"})


def _applies(rule: Rule, facts: CaseFacts) -> bool:
    gate = rule.applies_when
    if gate is None:
        return True
    return get_path(facts, gate.field) == gate.equals


def _not_applicable_result(rule: Rule, facts: CaseFacts) -> KindResult:
    gate = rule.applies_when
    assert gate is not None  # only called when the gate didn't match
    gate_value = get_path(facts, gate.field)
    quote = f"{gate.field} = {gate_value!r} (applies_when requires {gate.equals!r})"
    return KindResult(status="not_applicable", evidence=[EvidenceRef(kind="document", quote=quote)])


def _evaluate_per_document(rule: Rule, doc: DocumentFact) -> KindResult:
    match rule.kind:
        case "doc_type_match":
            params = DocTypeMatchParams.model_validate(rule.params)
            return kinds.evaluate_doc_type_match(params, doc)
        case "legibility":
            return kinds.evaluate_legibility(LegibilityParams.model_validate(rule.params), doc)
        case "injection_flag":
            return kinds.evaluate_injection_flag(
                InjectionFlagParams.model_validate(rule.params), doc
            )
        case _:  # pragma: no cover - unreachable: only called for _PER_DOCUMENT_KINDS
            raise AssertionError(f"{rule.kind!r} is not a per-document kind")


def _evaluate_single(rule: Rule, ctx: EvalContext) -> KindResult:
    match rule.kind:
        case "enum_match":
            return kinds.evaluate_enum_match(EnumMatchParams.model_validate(rule.params), ctx)
        case "date_not_expired":
            return kinds.evaluate_date_not_expired(
                DateNotExpiredParams.model_validate(rule.params), ctx
            )
        case "date_expiring_soon":
            return kinds.evaluate_date_expiring_soon(
                DateExpiringSoonParams.model_validate(rule.params), ctx
            )
        case "name_match":
            return kinds.evaluate_name_match(
                rule.id, NameMatchParams.model_validate(rule.params), ctx
            )
        case "registry_check":
            return kinds.evaluate_registry_check(
                rule.id, RegistryCheckParams.model_validate(rule.params), ctx
            )
        case "numeric_max":
            return kinds.evaluate_numeric_max(NumericMaxParams.model_validate(rule.params), ctx)
        case "numeric_min_pair":
            return kinds.evaluate_numeric_min_pair(
                NumericMinPairParams.model_validate(rule.params), ctx
            )
        case "presence_all":
            return kinds.evaluate_presence_all(PresenceAllParams.model_validate(rule.params), ctx)
        case "history_gap":
            return kinds.evaluate_history_gap(HistoryGapParams.model_validate(rule.params), ctx)
        case "checksum":
            return kinds.evaluate_checksum(ChecksumParams.model_validate(rule.params), ctx)
        case "path_route":
            return kinds.evaluate_path_route(PathRouteParams.model_validate(rule.params), ctx)
        case _:  # pragma: no cover - unreachable: _PER_DOCUMENT_KINDS covers the rest
            raise AssertionError(f"{rule.kind!r} is a per-document kind, not a single-value kind")


def _rule_source(rule: Rule, pack: RulePack) -> RuleSource:
    source = pack.sources[rule.source]
    return RuleSource(
        source_id=rule.source,
        url=source.url,
        doc_date=source.doc_date,
        last_verified=source.last_verified,
        needs_verification=rule.needs_verification,
    )


def evaluate_rule(rule: Rule, pack: RulePack, facts: CaseFacts, as_of: date) -> list[Finding]:
    """Evaluate one rule. Returns exactly one Finding, except for the three
    per-document kinds, which return one Finding per uploaded document (and
    zero if none are uploaded yet)."""
    rule_source = _rule_source(rule, pack)

    def _finding(finding_id: str, result: KindResult) -> Finding:
        return Finding(
            finding_id=finding_id,
            rule_id=rule.id,
            status=result.status,
            severity=rule.severity,
            evidence=result.evidence,
            rule_source=rule_source,
            confidence=result.confidence,
            decided_by="code",
        )

    if not _applies(rule, facts):
        return [_finding(rule.id, _not_applicable_result(rule, facts))]

    if rule.kind in _PER_DOCUMENT_KINDS:
        return [
            _finding(f"{rule.id}:{doc.doc_id}", _evaluate_per_document(rule, doc))
            for doc in facts.documents
        ]

    ctx = EvalContext(facts=facts, as_of=as_of, application_path=pack.application_path)
    return [_finding(rule.id, _evaluate_single(rule, ctx))]


def evaluate_rule_pack(pack: RulePack, facts: CaseFacts, as_of: date) -> list[Finding]:
    findings: list[Finding] = []
    for rule in pack.rules:
        findings.extend(evaluate_rule(rule, pack, facts, as_of))
    return findings

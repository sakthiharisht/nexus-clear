"""One pure function per rule kind (SPEC.md section 6).

Each `evaluate_*` function takes a rule's already-validated params model
(app/rules/schema.py) and an EvalContext, and returns a KindResult: the
Finding's status plus the evidence that backs it. No function here calls
`now()`, the network, or a model — `EvalContext.as_of` is passed in
explicitly (CLAUDE.md: "pure functions, no now(), explicit as_of").

app/rules/engine.py is the only caller; it handles `applies_when` gating
(before any of these run) and dispatches the three per-document kinds
(doc_type_match, legibility, injection_flag) once per uploaded document.
"""

from dataclasses import dataclass, field
from datetime import date

from app.core.contracts import EvidenceRef, FindingStatus
from app.rules.context import CaseFacts, DocumentFact, get_path, is_slot_readable
from app.rules.schema import (
    ApplicationPath,
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
    RegistryExclusionCheckParams,
    RegistryFlagsCheckParams,
    RegistryStatusCheckParams,
)


@dataclass(frozen=True)
class EvalContext:
    facts: CaseFacts
    as_of: date
    application_path: ApplicationPath


@dataclass(frozen=True)
class KindResult:
    status: FindingStatus
    evidence: list[EvidenceRef] = field(default_factory=list)
    confidence: float | None = None


def _doc_evidence(doc_id: str | None, quote: str) -> EvidenceRef:
    return EvidenceRef(kind="document", doc_id=doc_id, page=None, quote=quote)


def _registry_evidence(result_registry: str | None, tool: str, record_hash: str | None,
                        fetched_at: object, quote: str) -> EvidenceRef:
    return EvidenceRef(
        kind="registry",
        registry=result_registry or tool,
        record_hash=record_hash,
        fetched_at=fetched_at,  # type: ignore[arg-type]
        quote=quote,
    )


def _unknown(field_path: str) -> KindResult:
    return KindResult(
        status="unknown",
        evidence=[_doc_evidence(None, f"{field_path} is not known yet")],
    )


# ---- per-document kinds --------------------------------------------------


def evaluate_doc_type_match(_params: DocTypeMatchParams, doc: DocumentFact) -> KindResult:
    if doc.uploaded_doc_type is None:
        return _unknown(f"documents[{doc.doc_id}].uploaded_doc_type")
    quote = f"uploaded as {doc.uploaded_doc_type!r}, slot expects {doc.expected_doc_type!r}"
    status: FindingStatus = "pass" if doc.uploaded_doc_type == doc.expected_doc_type else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(doc.doc_id, quote)])


def evaluate_legibility(params: LegibilityParams, doc: DocumentFact) -> KindResult:
    if doc.legible_score is None:
        return _unknown(f"documents[{doc.doc_id}].legible_score")
    quote = f"legibility score {doc.legible_score} (minimum {params.min_score})"
    status: FindingStatus = "pass" if doc.legible_score >= params.min_score else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(doc.doc_id, quote)])


def evaluate_injection_flag(_params: InjectionFlagParams, doc: DocumentFact) -> KindResult:
    if doc.contains_injection_text is None:
        return _unknown(f"documents[{doc.doc_id}].contains_injection_text")
    quote = f"contains_injection_text={doc.contains_injection_text}"
    # fail = "the scan caught something" (surfaced at info severity — a flag,
    # not a blocker); pass = nothing found. See CLAUDE.md invariant 3.
    status: FindingStatus = "fail" if doc.contains_injection_text else "pass"
    return KindResult(status=status, evidence=[_doc_evidence(doc.doc_id, quote)])


# ---- per-case kinds -------------------------------------------------------


def evaluate_enum_match(params: EnumMatchParams, ctx: EvalContext) -> KindResult:
    value = get_path(ctx.facts, params.field)
    if value is None:
        return _unknown(params.field)
    quote = f"{params.field} = {value!r}"
    status: FindingStatus = "pass" if value in params.allowed else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def evaluate_date_not_expired(params: DateNotExpiredParams, ctx: EvalContext) -> KindResult:
    expiration = get_path(ctx.facts, params.field)
    if expiration is None:
        return _unknown(params.field)
    if not isinstance(expiration, date):
        return _unknown(params.field)

    status_note = ""
    if params.status_field is not None:
        status_value = get_path(ctx.facts, params.status_field)
        if status_value is None:
            return _unknown(params.status_field)
        active_values = params.active_values or []
        if status_value not in active_values:
            quote = f"{params.status_field} = {status_value!r} (not in {active_values})"
            return KindResult(status="fail", evidence=[_doc_evidence(None, quote)])
        status_note = f"; {params.status_field} = {status_value!r}"

    not_expired = expiration >= ctx.as_of
    quote = (
        f"{params.field} = {expiration.isoformat()}, as_of = {ctx.as_of.isoformat()}"
        f"{status_note}"
    )
    status: FindingStatus = "pass" if not_expired else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def evaluate_date_expiring_soon(params: DateExpiringSoonParams, ctx: EvalContext) -> KindResult:
    expiration = get_path(ctx.facts, params.field)
    if expiration is None or not isinstance(expiration, date):
        return _unknown(params.field)
    days_until = (expiration - ctx.as_of).days

    if days_until < 0:
        # Already expired: that's R-LIC-002's (date_not_expired) blocker to
        # report, not this warning — avoid double-reporting the same fact
        # as two separate findings.
        quote = (
            f"{params.field} = {expiration.isoformat()} already expired "
            f"as of {ctx.as_of.isoformat()}"
        )
        return KindResult(status="not_applicable", evidence=[_doc_evidence(None, quote)])

    quote = (
        f"{params.field} = {expiration.isoformat()}, {days_until} day(s) from as_of "
        f"(threshold {params.within_days})"
    )
    status: FindingStatus = "fail" if days_until <= params.within_days else "pass"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def evaluate_name_match(rule_id: str, params: NameMatchParams, ctx: EvalContext) -> KindResult:
    left_value = get_path(ctx.facts, params.left)
    right_value = get_path(ctx.facts, params.right)
    probability = ctx.facts.name_match_probabilities.get(rule_id)
    quote = f"{params.left} = {left_value!r} vs {params.right} = {right_value!r}"
    if params.alt_right is not None:
        alt_value = get_path(ctx.facts, params.alt_right)
        quote += f" (alt_right {params.alt_right} = {alt_value!r})"

    if probability is None:
        return KindResult(status="unknown", evidence=[_doc_evidence(None, quote)])

    quote += f"; resolved match probability = {probability}"
    status: FindingStatus = "pass" if probability >= params.min_probability else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)], confidence=probability)


def _no_registry_result_yet(tool: str) -> KindResult:
    return KindResult(
        status="unknown",
        evidence=[_doc_evidence(None, f"no registry result resolved yet for {tool}")],
    )


def evaluate_registry_status_check(
    rule_id: str, params: RegistryStatusCheckParams, ctx: EvalContext
) -> KindResult:
    result = ctx.facts.registry_results.get(rule_id)
    if result is None:
        return _no_registry_result_yet(params.tool)

    quote = f"{params.tool} status = {result.status!r} (expected {params.expect_status!r})"
    status: FindingStatus = "pass" if result.status == params.expect_status else "fail"
    evidence = _registry_evidence(
        result.registry, params.tool, result.record_hash, result.fetched_at, quote
    )
    return KindResult(status=status, evidence=[evidence])


def evaluate_registry_flags_check(
    rule_id: str, params: RegistryFlagsCheckParams, ctx: EvalContext
) -> KindResult:
    result = ctx.facts.registry_results.get(rule_id)
    if result is None:
        return _no_registry_result_yet(params.tool)

    missing = [flag for flag in params.expect if not result.checks.get(flag)]
    quote = f"{params.tool} checks = {result.checks!r} (required {params.expect!r})"
    status: FindingStatus = "fail" if missing else "pass"
    evidence = _registry_evidence(
        result.registry, params.tool, result.record_hash, result.fetched_at, quote
    )
    return KindResult(status=status, evidence=[evidence])


def evaluate_registry_exclusion_check(
    rule_id: str, params: RegistryExclusionCheckParams, ctx: EvalContext
) -> KindResult:
    result = ctx.facts.registry_results.get(rule_id)
    if result is None:
        return _no_registry_result_yet(params.tool)
    if result.possible_match is None:
        return KindResult(
            status="unknown",
            evidence=[_doc_evidence(None, f"{params.tool} possible_match not yet checked")],
        )

    quote = f"{params.tool} possible_match = {result.possible_match}"
    # A possible match can't be auto-resolved here — it goes to the reviewer
    # (SPEC.md section 7.7), so this engine reports `unknown` rather than
    # guessing pass or fail.
    status: FindingStatus = "unknown" if result.possible_match else "pass"
    evidence = _registry_evidence(
        result.registry, params.tool, result.record_hash, result.fetched_at, quote
    )
    return KindResult(status=status, evidence=[evidence])


def evaluate_numeric_max(params: NumericMaxParams, ctx: EvalContext) -> KindResult:
    value = get_path(ctx.facts, params.field)
    if value is None or not isinstance(value, (int, float)):
        return _unknown(params.field)
    quote = f"{params.field} = {value} (max {params.max})"
    status: FindingStatus = "pass" if value <= params.max else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def evaluate_numeric_min_pair(params: NumericMinPairParams, ctx: EvalContext) -> KindResult:
    values = [get_path(ctx.facts, f) for f in params.fields]
    if any(v is None or not isinstance(v, (int, float)) for v in values):
        return _unknown(", ".join(params.fields))
    quote = "; ".join(
        f"{f} = {v} (min {m})" for f, v, m in zip(params.fields, values, params.mins, strict=True)
    )
    status: FindingStatus = (
        "pass"
        if all(v >= m for v, m in zip(values, params.mins, strict=True))  # type: ignore[operator]
        else "fail"
    )
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def evaluate_presence_all(params: PresenceAllParams, ctx: EvalContext) -> KindResult:
    """Unlike most kinds, a missing field here isn't automatically
    `unknown` — presence_all's whole job is judging presence/absence, so a
    field that's blank on a document we actually read is a confirmed
    `fail`. Only when the owning document was never readable at all does
    that field's absence collapse to `unknown` (CLAUDE.md invariant 2: no
    guessing). `fail` wins over `unknown` when both occur in the same
    rule, since a confirmed-missing field is decisive regardless of what
    else couldn't be checked.
    """
    values = {f: get_path(ctx.facts, f) for f in params.fields}
    missing = [f for f, v in values.items() if v is None or v == ""]

    confirmed_missing = [f for f in missing if is_slot_readable(ctx.facts, f.split(".", 1)[0])]
    unreadable = [f for f in missing if f not in confirmed_missing]

    if confirmed_missing:
        quote = f"missing (document read): {confirmed_missing!r}"
        if unreadable:
            quote += f"; also unreadable: {unreadable!r}"
        return KindResult(status="fail", evidence=[_doc_evidence(None, quote)])

    if unreadable:
        quote = f"cannot confirm presence - document(s) unreadable: {unreadable!r}"
        return KindResult(status="unknown", evidence=[_doc_evidence(None, quote)])

    quote = f"present: {values!r}"
    return KindResult(status="pass", evidence=[_doc_evidence(None, quote)])


def evaluate_history_gap(params: HistoryGapParams, ctx: EvalContext) -> KindResult:
    positions = ctx.facts.cv.positions
    if not positions:
        return _unknown(params.field)
    if any(p.start is None for p in positions):
        return _unknown(f"{params.field}[].start")

    window_days = round(params.min_years * 365.25)
    window_start = ctx.as_of.fromordinal(ctx.as_of.toordinal() - window_days)

    intervals = sorted(
        (p.start, p.end or ctx.as_of) for p in positions if p.start is not None
    )
    merged: list[tuple[date, date]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    max_gap_days = 0
    cursor = window_start
    for start, end in merged:
        if start > cursor:
            max_gap_days = max(max_gap_days, (start - cursor).days)
        cursor = max(cursor, end)
    if cursor < ctx.as_of:
        max_gap_days = max(max_gap_days, (ctx.as_of - cursor).days)

    max_gap_months = max_gap_days / 30.44
    quote = (
        f"largest gap in {params.field} since {window_start.isoformat()} is "
        f"{max_gap_months:.1f} month(s) (threshold {params.max_gap_months})"
    )
    status: FindingStatus = "fail" if max_gap_months > params.max_gap_months else "pass"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def npi_check_digit(base9: str) -> int:
    """CMS "Requirements for National Provider Identifier (NPI) and NPI
    Check Digit": prepend the virtual prefix 80840 (80 = health
    applications, 840 = USA) to the 9-digit base, run the standard Luhn
    "double every second digit from the right" sum over the 14 resulting
    digits, and return the Luhn check digit. Verified against CMS's own
    worked example: base 123456789 -> check digit 3 -> NPI 1234567893.
    Shared by `npi_luhn_80840_valid` (validation) and the eval generator
    (synthetic NPI construction, app/eval/generator/npi.py) so both sides
    of the algorithm can never drift apart.
    """
    base = "80840" + base9
    total = 0
    for i, ch in enumerate(reversed(base), start=1):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def npi_luhn_80840_valid(npi: str) -> bool:
    """Validate a 10-digit NPI's check digit — see `npi_check_digit`."""
    if len(npi) != 10 or not npi.isdigit():
        return False
    return npi_check_digit(npi[:9]) == int(npi[9])


def evaluate_checksum(params: ChecksumParams, ctx: EvalContext) -> KindResult:
    value = get_path(ctx.facts, params.field)
    if value is None:
        return _unknown(params.field)
    if not isinstance(value, str):
        quote = f"{params.field} = {value!r} is not a string"
        return KindResult(status="fail", evidence=[_doc_evidence(None, quote)])
    quote = f"{params.field} = {value!r} ({params.algorithm})"
    valid = npi_luhn_80840_valid(value) if params.algorithm == "npi_luhn_80840" else False
    status: FindingStatus = "pass" if valid else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])


def evaluate_path_route(params: PathRouteParams, ctx: EvalContext) -> KindResult:
    quote = f"pack application_path = {ctx.application_path!r} (expected {params.path!r})"
    status: FindingStatus = "pass" if ctx.application_path == params.path else "fail"
    return KindResult(status=status, evidence=[_doc_evidence(None, quote)])

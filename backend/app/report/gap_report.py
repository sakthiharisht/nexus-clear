"""Gap report (SPEC.md section 7.8): plain-English explanations from
Findings only, verified before being trusted (CLAUDE.md invariant 1:
no model output may stand in for a code decision - here the decision
is whether a sentence is honest enough to show a provider).

Claude phrases (app/report/claude_phraser.py); this module is the
code-side verification SPEC 7.8 requires: every date, number, and name
Claude's sentence contains must already appear in that finding's own
evidence quotes, rule title, or rule source metadata - otherwise the
sentence is discarded and replaced with a deterministic template built
straight from the Finding, never from the model.

A rule marked `needs_verification` (CLAUDE.md: "must stay visible in
the UI") never gets a model-phrased sentence at all, regardless of
whether it would pass the check above - the "payer rule stated as
fact" risk SPEC 7.8 calls out is eliminated at the type level here,
not by trying to detect hedging language in free text after the fact.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.core.contracts import Finding
from app.report.types import PhraseRequest, SentencePhraser

_STATUS_WORD: dict[str, str] = {
    "pass": "meets this requirement",
    "fail": "does not meet this requirement",
    "unknown": "could not be confirmed from the documents provided",
    "not_applicable": "does not apply to this case",
}

# A sentence's claimed dates/numbers/names must each already appear in
# the finding's own evidence/rule text - this is deliberately a plain
# substring check, not date-equivalence or fuzzy name matching: the
# phraser's prompt requires dates verbatim in YYYY-MM-DD form exactly
# so this check can stay this simple and still be reliable.
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER_RE = re.compile(r"\$?\d[\d,]*\.?\d*")
_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+)+\b")

_PHRASE_WORTHY_STATUSES = {"fail", "unknown"}


def _haystack(finding: Finding, rule_title: str) -> str:
    parts = [rule_title, finding.rule_source.source_id, finding.rule_source.doc_date or ""]
    parts.extend(evidence.quote or "" for evidence in finding.evidence)
    return " ".join(parts)


def _claimed_tokens(sentence: str) -> list[str]:
    return [*_DATE_RE.findall(sentence), *_NUMBER_RE.findall(sentence), *_NAME_RE.findall(sentence)]


def _is_verified(sentence: str, haystack: str) -> bool:
    for token in _claimed_tokens(sentence):
        cleaned = token.strip().rstrip(".,;:")
        if cleaned and cleaned not in haystack:
            return False
    return True


def _template_sentence(finding: Finding, rule_title: str) -> str:
    word = _STATUS_WORD.get(finding.status, finding.status)
    hedge = (
        " (this rule is still flagged for independent verification - treat it "
        "as guidance, not a confirmed payer requirement)"
        if finding.rule_source.needs_verification
        else ""
    )
    quotes = "; ".join(evidence.quote for evidence in finding.evidence if evidence.quote)
    evidence_clause = f" Evidence: {quotes}." if quotes else ""
    return f"{rule_title}: {word}.{hedge}{evidence_clause}"


class GapReportEntry(BaseModel):
    finding_id: str
    rule_id: str
    rule_title: str
    status: str
    severity: str
    sentence: str
    sentence_model_phrased: bool
    source_id: str
    doc_date: str | None
    last_verified: str
    needs_verification: bool


class GapReport(BaseModel):
    readiness_score: int
    entries: list[GapReportEntry]
    simulated: bool = False


def _readiness_score(findings: list[Finding]) -> int:
    score = 100
    for finding in findings:
        if finding.status != "fail":
            continue
        if finding.severity == "blocker":
            score -= 25
        elif finding.severity == "warning":
            score -= 5
    return max(score, 0)


def build_gap_report(
    findings: list[Finding], *, rule_titles: dict[str, str], phraser: SentencePhraser
) -> GapReport:
    phrase_requests = [
        PhraseRequest(
            finding_id=finding.finding_id,
            rule_title=rule_titles.get(finding.rule_id, finding.rule_id),
            status=finding.status,
            evidence_quotes=[e.quote for e in finding.evidence if e.quote],
        )
        for finding in findings
        if finding.status in _PHRASE_WORTHY_STATUSES and not finding.rule_source.needs_verification
    ]
    phrase_result = phraser.phrase(phrase_requests)

    entries: list[GapReportEntry] = []
    for finding in findings:
        rule_title = rule_titles.get(finding.rule_id, finding.rule_id)
        sentence = _template_sentence(finding, rule_title)
        sentence_model_phrased = False

        model_sentence = phrase_result.sentences.get(finding.finding_id)
        eligible_for_model_phrasing = (
            finding.status in _PHRASE_WORTHY_STATUSES and not finding.rule_source.needs_verification
        )
        if (
            model_sentence is not None
            and eligible_for_model_phrasing
            and _is_verified(model_sentence, _haystack(finding, rule_title))
        ):
            sentence = model_sentence
            sentence_model_phrased = True

        entries.append(
            GapReportEntry(
                finding_id=finding.finding_id,
                rule_id=finding.rule_id,
                rule_title=rule_title,
                status=finding.status,
                severity=finding.severity,
                sentence=sentence,
                sentence_model_phrased=sentence_model_phrased,
                source_id=finding.rule_source.source_id,
                doc_date=finding.rule_source.doc_date,
                last_verified=finding.rule_source.last_verified,
                needs_verification=finding.rule_source.needs_verification,
            )
        )

    return GapReport(
        readiness_score=_readiness_score(findings),
        entries=entries,
        simulated=phrase_result.simulated,
    )

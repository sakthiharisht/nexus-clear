"""Tests for app/report/gap_report.py's deterministic verification and
fail-closed behavior, using a fake phraser (no live calls, no cache).
"""

from __future__ import annotations

from app.core.contracts import EvidenceRef, Finding, RuleSource
from app.report.gap_report import build_gap_report
from app.report.types import PhraseRequest, PhraseResult

_VERIFIED_SOURCE = RuleSource(
    source_id="s1", doc_date="2021-02-01", last_verified="2026-01-01", needs_verification=False
)
_UNVERIFIED_SOURCE = RuleSource(
    source_id="s2", doc_date=None, last_verified="2026-01-01", needs_verification=True
)


def _finding(
    finding_id: str,
    *,
    status: str = "fail",
    severity: str = "blocker",
    quote: str | None = "license.expiration_date = 2028-11-16, as_of = 2026-01-01",
    source: RuleSource = _VERIFIED_SOURCE,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        rule_id=finding_id,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        evidence=[EvidenceRef(kind="document", quote=quote)],
        rule_source=source,
        decided_by="code",
    )


class _FakePhraser:
    name = "fake"
    prompt_version = "test"

    def __init__(self, sentences: dict[str, str]) -> None:
        self._sentences = sentences
        self.requests: list[PhraseRequest] = []

    def phrase(self, requests: list[PhraseRequest]) -> PhraseResult:
        self.requests.extend(requests)
        return PhraseResult(
            sentences={
                r.finding_id: self._sentences[r.finding_id]
                for r in requests
                if r.finding_id in self._sentences
            }
        )


def test_a_verified_sentence_is_used_as_is() -> None:
    finding = _finding("R-LIC-002")
    phraser = _FakePhraser({"R-LIC-002": "Your license expires on 2028-11-16."})
    report = build_gap_report(
        [finding], rule_titles={"R-LIC-002": "License not expired"}, phraser=phraser
    )
    entry = report.entries[0]
    assert entry.sentence == "Your license expires on 2028-11-16."
    assert entry.sentence_model_phrased is True


def test_a_fabricated_date_falls_back_to_the_template() -> None:
    finding = _finding("R-LIC-002")
    phraser = _FakePhraser({"R-LIC-002": "Your license expires on 2030-01-01."})
    report = build_gap_report(
        [finding], rule_titles={"R-LIC-002": "License not expired"}, phraser=phraser
    )
    entry = report.entries[0]
    assert entry.sentence_model_phrased is False
    assert "License not expired" in entry.sentence
    assert "does not meet this requirement" in entry.sentence


def test_a_fabricated_name_falls_back_to_the_template() -> None:
    finding = _finding("R-LIC-004", quote="license.holder_name = 'Christopher Lee'")
    phraser = _FakePhraser(
        {"R-LIC-004": "The license is held by Jonathan Appleseed, not the applicant."}
    )
    report = build_gap_report(
        [finding], rule_titles={"R-LIC-004": "Name matches"}, phraser=phraser
    )
    assert report.entries[0].sentence_model_phrased is False


def test_needs_verification_never_gets_a_model_sentence_even_if_it_would_verify() -> None:
    # The quote is real and the sentence is accurate - but needs_verification
    # rules never reach the phraser at all (eliminated at the type level,
    # per the module's own docstring), so this must still fall back.
    finding = _finding(
        "R-LIC-001",
        quote="license.license_type = 'LPC Associate'",
        source=_UNVERIFIED_SOURCE,
    )
    phraser = _FakePhraser({"R-LIC-001": "The license type is LPC Associate."})
    report = build_gap_report(
        [finding], rule_titles={"R-LIC-001": "Full LPC required"}, phraser=phraser
    )
    assert phraser.requests == []
    entry = report.entries[0]
    assert entry.sentence_model_phrased is False
    assert "independent verification" in entry.sentence
    assert "not a confirmed payer requirement" in entry.sentence


def test_a_passing_finding_never_reaches_the_phraser() -> None:
    finding = _finding("R-LIC-002", status="pass")
    phraser = _FakePhraser({"R-LIC-002": "should never be requested"})
    build_gap_report([finding], rule_titles={"R-LIC-002": "x"}, phraser=phraser)
    assert phraser.requests == []


def test_missing_sentence_from_the_phraser_falls_back_to_the_template() -> None:
    finding = _finding("R-LIC-002")
    phraser = _FakePhraser({})  # phraser returned nothing for this finding_id
    report = build_gap_report([finding], rule_titles={"R-LIC-002": "x"}, phraser=phraser)
    assert report.entries[0].sentence_model_phrased is False


def test_readiness_score_subtracts_blocker_and_warning_fails() -> None:
    findings = [
        _finding("R-A", status="fail", severity="blocker"),
        _finding("R-B", status="fail", severity="warning"),
        _finding("R-C", status="pass", severity="blocker"),
        _finding("R-D", status="unknown", severity="blocker"),
    ]
    report = build_gap_report(findings, rule_titles={}, phraser=_FakePhraser({}))
    assert report.readiness_score == 100 - 25 - 5


def test_readiness_score_floors_at_zero() -> None:
    findings = [_finding(f"R-{i}", status="fail", severity="blocker") for i in range(10)]
    report = build_gap_report(findings, rule_titles={}, phraser=_FakePhraser({}))
    assert report.readiness_score == 0


def test_every_entry_maps_to_a_real_finding_id() -> None:
    findings = [_finding("R-A"), _finding("R-B", status="pass")]
    report = build_gap_report(findings, rule_titles={}, phraser=_FakePhraser({}))
    finding_ids = {f.finding_id for f in findings}
    assert {e.finding_id for e in report.entries} == finding_ids

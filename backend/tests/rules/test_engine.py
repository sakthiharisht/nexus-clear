"""Engine-level tests: applies_when gating (-> not_applicable), the
per-document fan-out for doc_type_match/legibility/injection_flag, rule
provenance, and a smoke run of the real seed pack end to end."""

from datetime import date
from pathlib import Path

from app.rules.context import (
    CaseFacts,
    CoiFacts,
    DocumentFact,
    LicenseFacts,
    ProfileFacts,
)
from app.rules.engine import evaluate_rule, evaluate_rule_pack
from app.rules.loader import load_rule_pack
from app.rules.schema import AppliesWhen, Rule, RulePack, Source

AS_OF = date(2026, 11, 17)
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


def _pack(rules: list[Rule]) -> RulePack:
    return RulePack(
        pack_id="test-pack",
        version="0.0.1",
        jurisdiction="TX",
        payer="TEST",
        provider_type="LPC",
        application_path="CAQH",
        target_date_default_offset_days=14,
        sources={
            "internal_policy": Source(last_verified="2026-11-03", notes="test fixture source"),
        },
        required_slots=[],
        rules=rules,
    )


# ---- applies_when gating ---------------------------------------------------


def test_applies_when_gate_not_matching_is_not_applicable() -> None:
    rule = Rule(
        id="R-TEST-SUP",
        title="Supervisor rule",
        severity="blocker",
        kind="numeric_max",
        params={"field": "supervision.supervisor_count", "max": 2},
        source="internal_policy",
        needs_verification=False,
        applies_when=AppliesWhen(field="license.license_type", equals="LPC Associate"),
    )
    pack = _pack([rule])
    facts = CaseFacts(target_date=AS_OF, license=LicenseFacts(license_type="LPC"))

    findings = evaluate_rule(rule, pack, facts, AS_OF)

    assert len(findings) == 1
    assert findings[0].status == "not_applicable"
    assert findings[0].evidence  # invariant: even not_applicable carries evidence


def test_applies_when_gate_matching_proceeds_to_kind_evaluation() -> None:
    rule = Rule(
        id="R-TEST-SUP",
        title="Supervisor rule",
        severity="blocker",
        kind="numeric_max",
        params={"field": "supervision.supervisor_count", "max": 2},
        source="internal_policy",
        needs_verification=False,
        applies_when=AppliesWhen(field="license.license_type", equals="LPC Associate"),
    )
    pack = _pack([rule])
    facts = CaseFacts(target_date=AS_OF, license=LicenseFacts(license_type="LPC Associate"))

    findings = evaluate_rule(rule, pack, facts, AS_OF)

    assert len(findings) == 1
    # supervision.supervisor_count wasn't set -> the numeric_max evaluator
    # (not the gate) is what decides this is unknown.
    assert findings[0].status == "unknown"


def test_rule_without_applies_when_always_proceeds() -> None:
    rule = Rule(
        id="R-TEST-ENUM",
        title="No gate",
        severity="blocker",
        kind="enum_match",
        params={"field": "license.license_type", "allowed": ["LPC"]},
        source="internal_policy",
        needs_verification=False,
    )
    pack = _pack([rule])
    facts = CaseFacts(target_date=AS_OF, license=LicenseFacts(license_type="LPC"))

    findings = evaluate_rule(rule, pack, facts, AS_OF)

    assert len(findings) == 1
    assert findings[0].status == "pass"


# ---- per-document fan-out ---------------------------------------------------


def test_per_document_kind_produces_one_finding_per_document() -> None:
    rule = Rule(
        id="R-TEST-DOC",
        title="Doc type match",
        severity="blocker",
        kind="doc_type_match",
        params={},
        source="internal_policy",
        needs_verification=False,
    )
    pack = _pack([rule])
    facts = CaseFacts(
        target_date=AS_OF,
        documents=[
            DocumentFact(
                doc_id="doc-a",
                slot="license",
                expected_doc_type="texas_lpc_license",
                uploaded_doc_type="texas_lpc_license",
            ),
            DocumentFact(
                doc_id="doc-b",
                slot="coi",
                expected_doc_type="malpractice_coi",
                uploaded_doc_type="cv",
            ),
        ],
    )

    findings = evaluate_rule(rule, pack, facts, AS_OF)

    assert len(findings) == 2
    by_id = {f.finding_id: f for f in findings}
    assert by_id["R-TEST-DOC:doc-a"].status == "pass"
    assert by_id["R-TEST-DOC:doc-b"].status == "fail"


def test_per_document_kind_produces_zero_findings_when_no_documents() -> None:
    rule = Rule(
        id="R-TEST-DOC",
        title="Doc type match",
        severity="blocker",
        kind="doc_type_match",
        params={},
        source="internal_policy",
        needs_verification=False,
    )
    pack = _pack([rule])
    facts = CaseFacts(target_date=AS_OF, documents=[])

    assert evaluate_rule(rule, pack, facts, AS_OF) == []


# ---- provenance -------------------------------------------------------------


def test_finding_carries_rule_source_and_needs_verification() -> None:
    rule = Rule(
        id="R-TEST-ENUM",
        title="No gate",
        severity="blocker",
        kind="enum_match",
        params={"field": "license.license_type", "allowed": ["LPC"]},
        source="internal_policy",
        needs_verification=True,
    )
    pack = _pack([rule])
    facts = CaseFacts(target_date=AS_OF, license=LicenseFacts(license_type="LPC"))

    finding = evaluate_rule(rule, pack, facts, AS_OF)[0]

    assert finding.rule_source.source_id == "internal_policy"
    assert finding.rule_source.needs_verification is True
    assert finding.decided_by == "code"


# ---- real seed pack smoke tests --------------------------------------------


def _clean_case_facts() -> CaseFacts:
    return CaseFacts(
        target_date=AS_OF,
        license=LicenseFacts(
            doc_id="doc-license",
            holder_name="Jane Provider",
            license_type="LPC",
            status="Active",
            expiration_date=date(2027, 6, 1),
        ),
        coi=CoiFacts(
            doc_id="doc-coi",
            insured_name="Jane Provider",
            carrier="Acme Ins",
            policy_number="P-123",
            effective_date=date(2026, 1, 1),
            expiration_date=date(2027, 1, 1),
            per_occurrence=100_000,
            aggregate=300_000,
        ),
        profile=ProfileFacts(legal_name="Jane Provider", npi="1234567893"),
        documents=[
            DocumentFact(
                doc_id="doc-license",
                slot="license",
                expected_doc_type="texas_lpc_license",
                uploaded_doc_type="texas_lpc_license",
                legible_score=0.95,
                contains_injection_text=False,
            ),
        ],
        name_match_probabilities={"R-LIC-004": 0.99, "R-COI-004": 0.99},
    )


def test_real_pack_loads_and_evaluates_without_error() -> None:
    pack = load_rule_pack(REAL_PACK_PATH)
    findings = evaluate_rule_pack(pack, _clean_case_facts(), AS_OF)
    assert len(findings) == 18  # one per rule; exactly one document uploaded
    assert all(f.evidence for f in findings)  # invariant 2: always evidence


def test_real_pack_clean_case_has_no_blocker_failures() -> None:
    pack = load_rule_pack(REAL_PACK_PATH)
    findings = evaluate_rule_pack(pack, _clean_case_facts(), AS_OF)
    blocker_fails = [f for f in findings if f.severity == "blocker" and f.status == "fail"]
    assert blocker_fails == []


def test_real_pack_associate_license_fails_enum_match_and_gates_supervisor_rules() -> None:
    pack = load_rule_pack(REAL_PACK_PATH)
    facts = _clean_case_facts()
    facts.license.license_type = "LPC Associate"

    findings = {f.rule_id: f for f in evaluate_rule_pack(pack, facts, AS_OF)}

    assert findings["R-LIC-001"].status == "fail"  # Associates may not practice independently
    assert findings["R-SUP-001"].status == "unknown"  # gate now matches; no registry result yet
    assert findings["R-SUP-002"].status == "unknown"  # gate now matches; no supervisor count yet


def test_real_pack_expired_license_fails_blocker_rule() -> None:
    pack = load_rule_pack(REAL_PACK_PATH)
    facts = _clean_case_facts()
    facts.license.expiration_date = date(2020, 1, 1)

    findings = {f.rule_id: f for f in evaluate_rule_pack(pack, facts, AS_OF)}

    assert findings["R-LIC-002"].status == "fail"
    assert findings["R-LIC-002"].severity == "blocker"


def test_real_pack_invalid_npi_fails_checksum_rule() -> None:
    pack = load_rule_pack(REAL_PACK_PATH)
    facts = _clean_case_facts()
    facts.profile.npi = "1234567890"  # wrong check digit

    findings = {f.rule_id: f for f in evaluate_rule_pack(pack, facts, AS_OF)}

    assert findings["R-ID-001"].status == "fail"

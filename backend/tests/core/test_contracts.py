from datetime import datetime

from app.core.contracts import EvidenceRef, Finding, RuleSource


def test_evidence_ref_document_kind() -> None:
    ev = EvidenceRef(kind="document", doc_id="doc-1", page=2, quote="Expires 2027-01-01")
    assert ev.kind == "document"
    assert ev.registry is None


def test_evidence_ref_registry_kind() -> None:
    ev = EvidenceRef(
        kind="registry",
        registry="nppes",
        record_hash="abc123",
        fetched_at=datetime(2026, 11, 1),
    )
    assert ev.kind == "registry"
    assert ev.doc_id is None


def test_finding_round_trip() -> None:
    rule_source = RuleSource(
        source_id="bhec_verify",
        url="https://bhec.texas.gov/?p=980",
        doc_date=None,
        last_verified="2026-11-03",
        needs_verification=False,
    )
    finding = Finding(
        finding_id="f-1",
        rule_id="R-LIC-002",
        status="pass",
        severity="blocker",
        evidence=[EvidenceRef(kind="document", doc_id="doc-1", page=1, quote="Active")],
        rule_source=rule_source,
        confidence=None,
        decided_by="code",
    )
    dumped = finding.model_dump()
    assert dumped["status"] == "pass"
    assert Finding.model_validate(dumped) == finding

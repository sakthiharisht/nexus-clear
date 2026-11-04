from __future__ import annotations

from datetime import date
from pathlib import Path

from app.reconcile.engine import reconcile
from app.reconcile.investigator import (
    InvestigationResult,
    NameMatchConclusion,
    NameMatchTask,
    RegistryConclusion,
    RegistryTask,
    ToolCallAuditEntry,
)
from app.rules.context import CaseFacts, LicenseFacts, ProfileFacts
from app.rules.loader import load_rule_pack

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = load_rule_pack(REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml")


class _FakeInvestigator:
    prompt_version = "test"

    def __init__(self, result: InvestigationResult) -> None:
        self.result = result
        self.calls: list[tuple[list[NameMatchTask], list[RegistryTask]]] = []

    def investigate(
        self, *, name_match_tasks: list[NameMatchTask], registry_tasks: list[RegistryTask]
    ) -> InvestigationResult:
        self.calls.append((name_match_tasks, registry_tasks))
        return self.result


def _facts(**overrides: object) -> CaseFacts:
    base = {
        "target_date": date(2026, 1, 1),
        "license": LicenseFacts(holder_name="Christopher Lee"),
        "profile": ProfileFacts(legal_name="Christopher Lee", npi="1000000004"),
    }
    base.update(overrides)
    return CaseFacts.model_validate(base)


def test_exact_name_match_resolves_without_calling_the_investigator_for_names() -> None:
    """clean-1-shaped case: holder_name == legal_name exactly, so
    R-LIC-004/R-COI-004 resolve in code - but registry rules still
    need the investigator, so it IS called (for registry_results),
    just not asked to resolve any name_match_tasks."""
    investigator = _FakeInvestigator(InvestigationResult())
    facts = _facts()
    result = reconcile(PACK, facts, investigator=investigator)

    assert result.name_match_probabilities.get("R-LIC-004") == 1.0
    assert investigator.calls
    name_match_tasks, _ = investigator.calls[0]
    assert name_match_tasks == []


def test_clear_mismatch_resolves_in_code_as_a_low_probability() -> None:
    facts = _facts(
        license=LicenseFacts(holder_name="Zachary Thompson"),
        profile=ProfileFacts(legal_name="Christopher Lee", npi="1000000004"),
    )
    investigator = _FakeInvestigator(InvestigationResult())
    result = reconcile(PACK, facts, investigator=investigator)
    assert result.name_match_probabilities["R-LIC-004"] <= 0.60


def test_ambiguous_name_match_is_sent_to_the_investigator() -> None:
    facts = _facts(
        license=LicenseFacts(holder_name="Jon Alvarez"),
        profile=ProfileFacts(legal_name="Jonathan Alvarez", npi="1000000004"),
    )
    investigator = _FakeInvestigator(
        InvestigationResult(
            name_match_conclusions=[
                NameMatchConclusion(rule_id="R-LIC-004", probability=0.9),
                NameMatchConclusion(rule_id="R-COI-004", probability=0.9),
            ]
        )
    )
    result = reconcile(PACK, facts, investigator=investigator)
    assert result.name_match_probabilities["R-LIC-004"] == 0.9
    _, _ = investigator.calls[0]
    name_match_tasks = investigator.calls[0][0]
    assert any(t.rule_id == "R-LIC-004" for t in name_match_tasks)


def test_registry_conclusion_record_hash_comes_from_the_audit_log_not_the_model() -> None:
    """The model's own submission never carries record_hash/fetched_at
    (see Investigator's docstring) - engine.py must pull those from
    the audit log entry it can actually trust."""
    facts = _facts()
    audit_entry = ToolCallAuditEntry(
        tool_name="nppes_lookup",
        query="1000000004",
        record_hash="abc123",
        mode="fixture",
    )
    investigator = _FakeInvestigator(
        InvestigationResult(
            registry_conclusions=[
                RegistryConclusion(
                    rule_id="R-ID-002",
                    exists=True,
                    checks={"exists": True, "name_consistent": True, "taxonomy_counselor": True},
                    # Model submits no record_hash - this is the normal,
                    # expected shape, not a degraded case.
                )
            ],
            audit_log=[audit_entry],
        )
    )
    result = reconcile(PACK, facts, investigator=investigator)
    assert result.registry_results["R-ID-002"].record_hash == "abc123"
    assert result.registry_results["R-ID-002"].registry == "nppes_lookup"


def test_a_registry_conclusion_with_no_matching_audit_entry_has_no_record_hash() -> None:
    facts = _facts()
    investigator = _FakeInvestigator(
        InvestigationResult(
            registry_conclusions=[RegistryConclusion(rule_id="R-ID-002", exists=True)],
            audit_log=[],
        )
    )
    result = reconcile(PACK, facts, investigator=investigator)
    assert result.registry_results["R-ID-002"].record_hash is None

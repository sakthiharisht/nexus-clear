"""Tests for app/eval/baseline_reconcile.py: deterministic (non-LLM) name
matching and registry fixture lookups.
"""

from pathlib import Path

import pytest

from app.eval.baseline_reconcile import (
    load_registry_fixtures,
    reconcile_name_matches,
    reconcile_registry_results,
)
from app.rules.context import CaseFacts, CoiFacts, LicenseFacts, ProfileFacts, SupervisionFacts
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return load_rule_pack(REAL_PACK_PATH)


def _facts(**overrides: object) -> CaseFacts:
    return CaseFacts(target_date="2026-11-17", **overrides)  # type: ignore[arg-type]


def test_exact_match_resolves_high(pack: RulePack) -> None:
    facts = _facts(
        license=LicenseFacts(holder_name="Christopher Lee"),
        profile=ProfileFacts(legal_name="Christopher Lee"),
    )
    probs = reconcile_name_matches(pack, facts)
    assert probs["R-LIC-004"] == 1.0


def test_clear_mismatch_resolves_low(pack: RulePack) -> None:
    facts = _facts(
        license=LicenseFacts(holder_name="Unrelated Stranger Smith"),
        profile=ProfileFacts(legal_name="Melanie Sullivan MD"),
    )
    probs = reconcile_name_matches(pack, facts)
    assert "R-LIC-004" in probs
    assert probs["R-LIC-004"] <= 0.60


def test_ambiguous_nickname_pair_is_left_unresolved(pack: RulePack) -> None:
    # The SPEC.md section 7.5 fixture case: rapidfuzz alone (no nickname
    # table) can't confidently call this one either way.
    facts = _facts(
        license=LicenseFacts(holder_name="Jon Alvarez"),
        profile=ProfileFacts(legal_name="Jonathan Alvarez"),
    )
    probs = reconcile_name_matches(pack, facts)
    assert "R-LIC-004" not in probs


def test_alt_right_fallback_takes_the_max_of_both_candidates(pack: RulePack) -> None:
    # R-COI-004 compares coi.insured_name against profile.legal_name OR
    # profile.practice_name (alt_right) - a match against either resolves.
    facts = _facts(
        coi=CoiFacts(insured_name="Acme Counseling PLLC"),
        profile=ProfileFacts(
            legal_name="Someone Else Entirely", practice_name="Acme Counseling PLLC"
        ),
    )
    probs = reconcile_name_matches(pack, facts)
    assert probs["R-COI-004"] == 1.0


def test_missing_left_field_is_skipped_not_guessed(pack: RulePack) -> None:
    facts = _facts(
        license=LicenseFacts(holder_name=None), profile=ProfileFacts(legal_name="Someone")
    )
    probs = reconcile_name_matches(pack, facts)
    assert "R-LIC-004" not in probs


def test_missing_right_and_alt_right_is_skipped_not_guessed(pack: RulePack) -> None:
    facts = _facts(
        coi=CoiFacts(insured_name="Acme Counseling PLLC"),
        profile=ProfileFacts(legal_name=None, practice_name=None),
    )
    probs = reconcile_name_matches(pack, facts)
    assert "R-COI-004" not in probs


def test_load_registry_fixtures_reads_the_real_committed_files() -> None:
    fixtures = load_registry_fixtures(REPO_ROOT / "eval" / "fixtures")
    assert set(fixtures) == {"nppes", "tx_license", "leie"}
    assert len(fixtures["nppes"]) == 12  # one per packet


def test_load_registry_fixtures_missing_dir_returns_empty(tmp_path: Path) -> None:
    fixtures = load_registry_fixtures(tmp_path)
    assert fixtures == {"nppes": {}, "tx_license": {}, "leie": {}}


def test_registry_status_check_resolves_from_supervisor_license_number(pack: RulePack) -> None:
    facts = _facts(
        supervision=SupervisionFacts(supervisor_license_number="LPC-100000-SUPERVISOR")
    )
    registry = {
        "nppes": {},
        "tx_license": {"LPC-100000-SUPERVISOR": {"status": "Active"}},
        "leie": {},
    }
    results = reconcile_registry_results(pack, facts, registry)
    assert results["R-SUP-001"].status == "Active"


def test_registry_flags_check_resolves_from_npi(pack: RulePack) -> None:
    facts = _facts(profile=ProfileFacts(npi="1000000004"))
    nppes_entry = {"exists": True, "name_consistent": True, "taxonomy_counselor": False}
    registry = {"nppes": {"1000000004": nppes_entry}, "tx_license": {}, "leie": {}}
    results = reconcile_registry_results(pack, facts, registry)
    assert results["R-ID-002"].checks == {
        "exists": True,
        "name_consistent": True,
        "taxonomy_counselor": False,
    }


def test_registry_exclusion_check_resolves_from_legal_name(pack: RulePack) -> None:
    facts = _facts(profile=ProfileFacts(legal_name="Katherine Robinson"))
    registry = {
        "nppes": {},
        "tx_license": {},
        "leie": {"Katherine Robinson": {"possible_match": True}},
    }
    results = reconcile_registry_results(pack, facts, registry)
    assert results["R-EXC-001"].possible_match is True


def test_registry_lookup_with_no_matching_entry_is_unresolved(pack: RulePack) -> None:
    facts = _facts(profile=ProfileFacts(npi="9999999999", legal_name="Nobody Here"))
    registry = {"nppes": {}, "tx_license": {}, "leie": {}}
    results = reconcile_registry_results(pack, facts, registry)
    assert "R-ID-002" not in results
    assert "R-EXC-001" not in results

"""M7 acceptance criteria (SPEC.md section 7.5 / section 14):

1. The nickname benign case (Christopher/Chris) passes.
2. A genuine name mismatch fails or escalates.
3. The LEIE possible-match packet is found and returns unknown plus
   an escalation.
4. The request limit is enforced (tests/reconcile/test_investigator.py
   ::test_request_limit_is_enforced - not duplicated here).

Each scenario runs the real pipeline: app/reconcile/engine.py's
reconcile() (code-only fast path + Investigator for anything
ambiguous or registry-backed) feeding app/rules/engine.py's
evaluate_rule_pack() (the actual rules engine Validate runs) - the
same two stages a real case would go through, not a shortcut around
either. Replay-mode (no API key needed, runs in CI) reads real
recorded investigations from the committed model cache; one live test
per scenario re-verifies against a fresh real call (skipif no key).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.reconcile.cache import CachedInvestigator
from app.reconcile.engine import reconcile
from app.reconcile.investigator import Investigator
from app.rules.context import CaseFacts, CoiFacts, LicenseFacts, ProfileFacts
from app.rules.engine import evaluate_rule_pack
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack
from app.tools_mcp.server import build_mcp_server

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
_HAS_ANTHROPIC_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"
REGISTRY_FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures" / "registry"
MODEL_CACHE_ROOT = REPO_ROOT / "eval" / "fixtures" / "model_cache"
GROUND_TRUTH_PATH = REPO_ROOT / "eval" / "fixtures" / "ground_truth.json"
_MODEL = "claude-haiku-5-5"
_TARGET_DATE = date(2026, 1, 1)

PACK = load_rule_pack(RULE_PACK_PATH)


def _nickname_facts() -> CaseFacts:
    return CaseFacts(
        target_date=_TARGET_DATE,
        license=LicenseFacts(holder_name="Chris Donovan"),
        coi=CoiFacts(insured_name="Chris Donovan"),
        profile=ProfileFacts(legal_name="Christopher Donovan", npi="9999999997"),
    )


def _mismatch_facts() -> CaseFacts:
    return CaseFacts(
        target_date=_TARGET_DATE,
        license=LicenseFacts(holder_name="Jon Smith"),
        coi=CoiFacts(insured_name="Jon Smith"),
        profile=ProfileFacts(legal_name="John Smyth", npi="9999999998"),
    )


def _lic004_status(pack: RulePack, facts: CaseFacts) -> str:
    findings = evaluate_rule_pack(pack, facts, _TARGET_DATE)
    finding = next(f for f in findings if f.finding_id.startswith("R-LIC-004"))
    return finding.status


class _FailOnCallInvestigator:
    def investigate(self, *, name_match_tasks, registry_tasks):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "replay-mode acceptance test hit a cache miss and tried a real "
            "call - re-seed eval/fixtures/model_cache/claude/ for this case"
        )


def _replay_investigator() -> CachedInvestigator:
    return CachedInvestigator(
        _FailOnCallInvestigator(), model=_MODEL, cache_root=MODEL_CACHE_ROOT, mode="replay"
    )


def _live_investigator() -> Investigator:
    mcp = build_mcp_server(
        mode="fixture",
        fixtures_root=REGISTRY_FIXTURES_ROOT,
        rule_pack_path=RULE_PACK_PATH,
        leie_cache_path=REPO_ROOT / "data" / "cache" / "leie_updated.csv",
    )
    return Investigator(mcp, model=_MODEL, max_tool_calls=6)


def test_nickname_benign_case_passes_replay() -> None:
    facts = reconcile(PACK, _nickname_facts(), investigator=_replay_investigator())
    assert facts.name_match_probabilities["R-LIC-004"] >= 0.9
    assert _lic004_status(PACK, facts) == "pass"


@pytest.mark.skipif(not _HAS_ANTHROPIC_KEY, reason="no ANTHROPIC_API_KEY in backend/.env")
def test_nickname_benign_case_passes_live() -> None:
    facts = reconcile(PACK, _nickname_facts(), investigator=_live_investigator())
    assert _lic004_status(PACK, facts) == "pass"


def test_genuine_name_mismatch_fails_or_escalates_replay() -> None:
    facts = reconcile(PACK, _mismatch_facts(), investigator=_replay_investigator())
    assert _lic004_status(PACK, facts) in ("fail", "unknown")


@pytest.mark.skipif(not _HAS_ANTHROPIC_KEY, reason="no ANTHROPIC_API_KEY in backend/.env")
def test_genuine_name_mismatch_fails_or_escalates_live() -> None:
    facts = reconcile(PACK, _mismatch_facts(), investigator=_live_investigator())
    assert _lic004_status(PACK, facts) in ("fail", "unknown")


def _defective_8_facts() -> CaseFacts:
    import json

    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    packet = next(p for p in ground_truth["packets"] if p["packet_id"] == "defective-8")
    return CaseFacts.model_validate(packet["facts"])


def test_leie_possible_match_returns_unknown_replay() -> None:
    """defective-8 plants D12: a synthetic LEIE possible-match row.
    evaluate_registry_exclusion_check reports `unknown`, never pass or
    fail, for a possible match - that is the documented hand-off to a
    human reviewer (SPEC.md section 7.7), not an auto-decision.
    Also pins R-ID-002 (registry_flags_check) == "pass": this packet's
    real NPPES fixture entry has every flag true, a regression test
    for a real bug this project hit - the Investigator once reported
    `exists` only at the RegistryConclusion's top level, never inside
    `checks`, so evaluate_registry_flags_check's `checks.get("exists")`
    came back falsy and R-ID-002 failed even though every flag the
    tool returned was true."""
    facts = reconcile(PACK, _defective_8_facts(), investigator=_replay_investigator())
    assert facts.registry_results["R-EXC-001"].possible_match is True
    assert facts.registry_results["R-ID-002"].checks == {
        "exists": True,
        "name_consistent": True,
        "taxonomy_counselor": True,
    }
    findings = evaluate_rule_pack(PACK, facts, facts.target_date)
    exc001 = next(f for f in findings if f.finding_id.startswith("R-EXC-001"))
    id002 = next(f for f in findings if f.finding_id.startswith("R-ID-002"))
    assert exc001.status == "unknown"
    assert id002.status == "pass"


@pytest.mark.skipif(not _HAS_ANTHROPIC_KEY, reason="no ANTHROPIC_API_KEY in backend/.env")
def test_leie_possible_match_returns_unknown_live() -> None:
    facts = reconcile(PACK, _defective_8_facts(), investigator=_live_investigator())
    findings = evaluate_rule_pack(PACK, facts, facts.target_date)
    exc001 = next(f for f in findings if f.finding_id.startswith("R-EXC-001"))
    id002 = next(f for f in findings if f.finding_id.startswith("R-ID-002"))
    assert exc001.status == "unknown"
    assert id002.status == "pass"

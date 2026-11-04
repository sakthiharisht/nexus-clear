"""Integration test for app/eval/escalate_run.py against the real
committed model_cache (replay mode - no API key, no network). Reuses
the exact same real-fixture-driven pattern as tests/eval/test_run.py
and tests/reconcile/test_acceptance.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.backends.claude_extractor import ClaudeExtractor
from app.backends.extract_cache import CachedExtractor
from app.escalate.engine import EscalationThresholds
from app.eval.escalate_run import GROUND_TRUTH_ESCALATIONS, run_escalate_eval
from app.reconcile.cache import CachedInvestigator
from app.reconcile.investigator import Investigator
from app.rules.loader import load_rule_pack
from app.tools_mcp.server import build_mcp_server

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"
PACK = load_rule_pack(REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml")
MODEL_CACHE_ROOT = FIXTURES_ROOT / "model_cache"
_MODEL = "claude-haiku-5-5"
_THRESHOLDS = EscalationThresholds(low_confidence_threshold=0.60, blocker_confidence_threshold=0.90)


def _replay_extractor() -> CachedExtractor:
    return CachedExtractor(
        ClaudeExtractor(model=_MODEL), model=_MODEL, cache_root=MODEL_CACHE_ROOT, mode="replay"
    )


def _replay_investigator() -> CachedInvestigator:
    mcp = build_mcp_server(
        mode="fixture",
        fixtures_root=FIXTURES_ROOT / "registry",
        rule_pack_path=REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml",
        leie_cache_path=REPO_ROOT / "data" / "cache" / "leie_updated.csv",
    )
    return CachedInvestigator(
        Investigator(mcp, model=_MODEL, max_tool_calls=6),
        model=_MODEL,
        cache_root=MODEL_CACHE_ROOT,
        mode="replay",
    )


def test_escalate_eval_against_the_real_twelve_packet_corpus() -> None:
    result = run_escalate_eval(
        PACK,
        GROUND_TRUTH,
        FIXTURES_ROOT,
        mode_name="escalate-test",
        extractor=_replay_extractor(),
        investigator=_replay_investigator(),
        thresholds=_THRESHOLDS,
    )
    assert result.total_findings > 0
    assert 0.0 <= result.escalation_rate <= 1.0
    assert result.simulated is False

    # All four of this corpus's known escalation-relevant defects (two
    # genuine name mismatches, an LEIE possible-match, an injection
    # flag) must be caught, with nothing escalating outside this
    # labeled set either - a true positive on every actual escalation,
    # not just a subset of them.
    assert result.escalated_count == len(GROUND_TRUTH_ESCALATIONS)
    assert result.true_positives == len(GROUND_TRUTH_ESCALATIONS)
    assert result.false_positives == 0
    assert result.false_negatives == 0
    assert result.precision == 1.0
    assert result.recall == 1.0

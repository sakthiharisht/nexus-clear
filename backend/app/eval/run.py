"""M3 eval runner: `uv run python -m app.eval.run --config eval/config.yaml`
(run from the repo root — see eval/config.yaml).

Two modes (SPEC.md section 14's M3, as refined for this project):
  ceiling  - rules engine run directly on ground-truth CaseFacts. Must be
             100% — a sanity check on the engine and the hand-authored
             ground truth, not a real measurement.
  baseline - rules engine run on CaseFacts built by non-LLM extraction
             (app/eval/baseline_extraction.py: PDF text layer + regex,
             never guesses) from the rendered packets. This is the number
             any future LLM-backed stage has to beat.

No LLM calls anywhere in this module or anything it imports (CLAUDE.md /
SPEC.md: the rules-only baseline must exist and be offline-deterministic
before any LLM stage is added).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.backends.cache import CachedBackend
from app.backends.claude_backend import ClaudeBackend
from app.backends.claude_extractor import ClaudeExtractor
from app.backends.extract_cache import CachedExtractor, ExtractionBackend
from app.backends.factory import build_primary_and_fallback
from app.backends.jev_backend import JevBackend
from app.core.config import settings as app_settings
from app.eval.baseline_extraction import extract_baseline_facts
from app.eval.baseline_reconcile import (
    load_registry_fixtures,
    reconcile_name_matches,
    reconcile_registry_results,
)
from app.eval.classify_metrics import ClassifyMetrics, compute_classify_metrics
from app.eval.classify_run import run_classify
from app.eval.classify_types import ClassifyModeResult
from app.eval.extract_baseline_run import run_extract_baseline
from app.eval.extract_metrics import ExtractMetrics, compute_extract_metrics
from app.eval.extract_run import run_extract
from app.eval.extract_types import ExtractModeResult
from app.eval.metrics import compute_mode_metrics
from app.eval.report import render_markdown_report
from app.eval.types import ModeResult, PacketResult
from app.rules.context import CaseFacts
from app.rules.engine import evaluate_rule_pack
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]

# M5.1: report accuracy/ECE/escalation/tokens/cost/latency per Claude
# tier, not just the one model the policy's fallback actually uses.
CLAUDE_TIER_MODELS = {
    "classify-claude-haiku": "claude-haiku-5-5",
    "classify-claude-sonnet": "claude-sonnet-5-5",
    "classify-claude-opus": "claude-opus-5-5",
}

# M6: same per-tier reporting, for Extract.
EXTRACT_TIER_MODELS = {
    "extract-claude-haiku": "claude-haiku-5-5",
    "extract-claude-sonnet": "claude-sonnet-5-5",
    "extract-claude-opus": "claude-opus-5-5",
}


def _resolve(path_str: str, repo_root: Path) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else repo_root / path


def load_config(config_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path}: eval config must be a YAML mapping")
    return raw


def run_ceiling(pack: RulePack, ground_truth: dict[str, Any]) -> ModeResult:
    """Rules engine on ground-truth CaseFacts directly — no extraction."""
    packets: list[PacketResult] = []
    for packet in ground_truth["packets"]:
        facts = CaseFacts.model_validate(packet["facts"])
        target_date = date.fromisoformat(packet["target_date"])
        findings = evaluate_rule_pack(pack, facts, target_date)
        packets.append(
            PacketResult(
                packet_id=packet["packet_id"],
                kind=packet["kind"],
                defect_ids=packet["defect_ids"],
                actual={f.finding_id: f.status for f in findings},
                expected=packet["expected_findings"],
            )
        )
    return ModeResult(mode="ceiling", packets=packets)


def run_baseline(pack: RulePack, ground_truth: dict[str, Any], fixtures_root: Path) -> ModeResult:
    """Rules engine on CaseFacts built by non-LLM extraction
    (app/eval/baseline_extraction.py) plus non-LLM reconcile (rapidfuzz
    name matching + registry fixture lookups, app/eval/baseline_reconcile.py)
    from the rendered packets."""
    registry_fixtures = load_registry_fixtures(fixtures_root)
    packets: list[PacketResult] = []
    for packet in ground_truth["packets"]:
        facts, notes = extract_baseline_facts(packet, fixtures_root)
        facts = facts.model_copy(
            update={
                "name_match_probabilities": reconcile_name_matches(pack, facts),
                "registry_results": reconcile_registry_results(pack, facts, registry_fixtures),
            }
        )
        target_date = date.fromisoformat(packet["target_date"])
        findings = evaluate_rule_pack(pack, facts, target_date)
        packets.append(
            PacketResult(
                packet_id=packet["packet_id"],
                kind=packet["kind"],
                defect_ids=packet["defect_ids"],
                actual={f.finding_id: f.status for f in findings},
                expected=packet["expected_findings"],
                extraction_notes=notes,
            )
        )
    return ModeResult(mode="baseline", packets=packets)


def _cached(backend: Any, model: str) -> CachedBackend:
    return CachedBackend(
        backend,
        model=model,
        cache_root=app_settings.model_cache_root,
        mode=app_settings.model_cache_mode,
    )


def run_classify_mode(
    mode_name: str, ground_truth: dict[str, Any], fixtures_root: Path
) -> ClassifyModeResult:
    """Dispatches a classify eval mode by name (eval/config.yaml's
    `classify_modes` / `classify_modes_hard`):

    - "classify-jev" / "classify-claude-{haiku,sonnet,opus}": the
      backend alone, no fallback - raw per-backend/per-tier accuracy/
      calibration. Constructed directly (not via app.backends.factory,
      which refuses to build a Jev backend with no JEV_API_KEY
      configured - a correct guard for a live deployment, but the
      cache/replay path these eval runs use never needs a key at all).
    - "classify-policy-claude": app.backends.factory's real wiring,
      forced to DECISION_BACKEND=claude regardless of the ambient env
      - the exact path CLAUDE.md invariant 6 requires to work end to
      end with zero Jev involvement. Always the haiku tier
      (MODEL_CLASSIFY_FALLBACK), matching the real policy's cheap-tier
      fallback - not whichever tier happens to run alongside it.

    A trailing "-hard" (M5.1 housekeeping #2's hard classify set,
    app/eval/generator/hard_classify_set.py) is stripped before
    dispatch but kept in the mode name `run_classify` actually returns
    - the hard set uses a different `ground_truth`/`fixtures_root`, not
    a different backend/tier, so the two sets land as separate rows
    rather than silently pooling into one average.
    """
    base_mode_name = mode_name.removesuffix("-hard")
    if base_mode_name == "classify-jev":
        primary: Any = _cached(
            JevBackend(api_key=app_settings.jev_api_key or "unset", model=app_settings.jev_model),
            app_settings.jev_model,
        )
        fallback = None
    elif base_mode_name in CLAUDE_TIER_MODELS:
        model = CLAUDE_TIER_MODELS[base_mode_name]
        primary = _cached(ClaudeBackend(model=model), model)
        fallback = None
    elif base_mode_name == "classify-policy-claude":
        claude_settings = app_settings.model_copy(update={"decision_backend": "claude"})
        primary, fallback = build_primary_and_fallback(claude_settings)
    else:
        raise ValueError(f"unknown classify mode: {mode_name!r}")

    return run_classify(
        ground_truth,
        fixtures_root,
        mode_name=mode_name,
        primary=primary,
        fallback=fallback,
        tau_classify=app_settings.tau_classify,
        legible_threshold=app_settings.legible_threshold,
    )


def _cached_extractor(backend: ExtractionBackend, model: str) -> CachedExtractor:
    return CachedExtractor(
        backend,
        model=model,
        cache_root=app_settings.model_cache_root,
        mode=app_settings.model_cache_mode,
    )


def run_extract_mode(
    mode_name: str, ground_truth: dict[str, Any], fixtures_root: Path
) -> ExtractModeResult:
    """Dispatches an extract eval mode by name (eval/config.yaml's
    `extract_modes`): "extract-baseline" (M3's regex-only extractor,
    app/eval/baseline_extraction.py - no model, no cache) or
    "extract-claude-{haiku,sonnet,opus}" (app/backends/claude_extractor.py,
    through the same record/replay cache Classify's tiers use)."""
    if mode_name == "extract-baseline":
        return run_extract_baseline(ground_truth, fixtures_root)
    if mode_name in EXTRACT_TIER_MODELS:
        model = EXTRACT_TIER_MODELS[mode_name]
        backend = _cached_extractor(ClaudeExtractor(model=model), model)
        return run_extract(ground_truth, fixtures_root, mode_name=mode_name, backend=backend)
    raise ValueError(f"unknown extract mode: {mode_name!r}")


def run_eval(config: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    rule_pack_path = _resolve(config["rule_pack"], repo_root)
    ground_truth_path = _resolve(config["ground_truth"], repo_root)
    fixtures_root = _resolve(config["fixtures_root"], repo_root)

    pack = load_rule_pack(rule_pack_path)
    ground_truth: dict[str, Any] = json.loads(ground_truth_path.read_text(encoding="utf-8"))

    mode_results: dict[str, ModeResult] = {}
    if "ceiling" in config["modes"]:
        mode_results["ceiling"] = run_ceiling(pack, ground_truth)
    if "baseline" in config["modes"]:
        mode_results["baseline"] = run_baseline(pack, ground_truth, fixtures_root)

    # Keyed by result.mode, not the requested mode_name: run_classify
    # appends "-SIMULATED" to the mode name itself when any document in
    # it came from a simulated fixture (app/eval/classify_run.py), so
    # the dict key here - which becomes the JSON key and the markdown
    # table's row label - carries that marker too, not just the field
    # inside each document.
    classify_results: dict[str, ClassifyModeResult] = {}
    for mode_name in config.get("classify_modes", []):
        result = run_classify_mode(mode_name, ground_truth, fixtures_root)
        classify_results[result.mode] = result

    # M5.1 housekeeping #2: the hard classify set is a different
    # ground_truth/fixtures_root entirely (not just different mode
    # names), so it needs its own load - run_classify_mode still
    # dispatches by stripping the "-hard" suffix.
    if "classify_modes_hard" in config:
        hard_ground_truth_path = _resolve(config["hard_ground_truth"], repo_root)
        hard_fixtures_root = _resolve(config["hard_fixtures_root"], repo_root)
        hard_ground_truth: dict[str, Any] = json.loads(
            hard_ground_truth_path.read_text(encoding="utf-8")
        )
        for mode_name in config["classify_modes_hard"]:
            result = run_classify_mode(mode_name, hard_ground_truth, hard_fixtures_root)
            classify_results[result.mode] = result

    classify_metrics: dict[str, ClassifyMetrics] = {
        mode_name: compute_classify_metrics(result)
        for mode_name, result in classify_results.items()
    }

    extract_results: dict[str, ExtractModeResult] = {}
    for mode_name in config.get("extract_modes", []):
        extract_result = run_extract_mode(mode_name, ground_truth, fixtures_root)
        extract_results[extract_result.mode] = extract_result

    extract_metrics: dict[str, ExtractMetrics] = {
        mode_name: compute_extract_metrics(result)
        for mode_name, result in extract_results.items()
    }

    return {
        "rule_pack_version": pack.version,
        "ground_truth_seed": ground_truth["seed"],
        "modes": {mode: result.model_dump(mode="json") for mode, result in mode_results.items()},
        "metrics": {
            mode: compute_mode_metrics(result, pack).model_dump(mode="json")
            for mode, result in mode_results.items()
        },
        "classify_modes": {
            mode: result.model_dump(mode="json") for mode, result in classify_results.items()
        },
        "classify_metrics": {
            mode: metrics.model_dump(mode="json") for mode, metrics in classify_metrics.items()
        },
        "extract_modes": {
            mode: result.model_dump(mode="json") for mode, result in extract_results.items()
        },
        "extract_metrics": {
            mode: metrics.model_dump(mode="json") for mode, metrics in extract_metrics.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rules-only eval baseline (SPEC.md section 14, M3)"
    )
    parser.add_argument("--config", default="eval/config.yaml")
    args = parser.parse_args()

    # Same convention as every path inside the config itself: relative to
    # the repo root regardless of invocation cwd (so the documented command
    # works whether run from the repo root or from backend/).
    config_path = _resolve(args.config, REPO_ROOT)
    config = load_config(config_path)
    result = run_eval(config, REPO_ROOT)

    output_dir = _resolve(config["output_dir"], REPO_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_path = output_dir / f"run-{timestamp}.json"
    run_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(render_markdown_report(result))
    print(f"\nWrote {run_path}")


if __name__ == "__main__":  # pragma: no cover
    main()

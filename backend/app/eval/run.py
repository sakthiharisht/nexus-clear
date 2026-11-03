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

from app.eval.baseline_extraction import extract_baseline_facts
from app.eval.metrics import compute_mode_metrics
from app.eval.report import render_markdown_report
from app.eval.types import ModeResult, PacketResult
from app.rules.context import CaseFacts
from app.rules.engine import evaluate_rule_pack
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]


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
    """Rules engine on CaseFacts built by non-LLM extraction from the
    rendered packets — see app/eval/baseline_extraction.py."""
    packets: list[PacketResult] = []
    for packet in ground_truth["packets"]:
        facts, notes = extract_baseline_facts(packet, fixtures_root)
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

    return {
        "rule_pack_version": pack.version,
        "ground_truth_seed": ground_truth["seed"],
        "modes": {mode: result.model_dump(mode="json") for mode, result in mode_results.items()},
        "metrics": {
            mode: compute_mode_metrics(result, pack).model_dump(mode="json")
            for mode, result in mode_results.items()
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

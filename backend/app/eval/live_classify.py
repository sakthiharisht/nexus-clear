"""Live classify runner (M5.1): makes REAL calls against Claude (and
Jev, if JEV_API_KEY is set) over all 60 real documents (12 packets x 5
slots) and records genuine responses into eval/fixtures/model_cache/,
replacing app/eval/classify_fixture_seed.py's simulated placeholders.

NOT run automatically anywhere - not by pytest, not by CI. This spends
real money and makes real network calls. Invoke explicitly:

    uv run python -m app.eval.live_classify
    uv run python -m app.eval.live_classify --cost-ceiling 2.0 --max-calls 100
    uv run python -m app.eval.live_classify --claude-only

Requires ANTHROPIC_API_KEY (backend/.env, loaded via python-dotenv -
app.core.config.settings only loads .env for its own declared fields,
and ANTHROPIC_API_KEY isn't one of them since the anthropic SDK reads
it directly from the process environment). JEV_API_KEY is optional -
when absent, Jev is skipped entirely and stays on simulated fixtures.

Cost/call ceiling: every live call (a genuine cache miss that reaches
the real backend, not a cache hit) is checked against both a running
cost total and a running call count *before* it's made. Crossing
either aborts the whole run immediately with a clear error - never a
silent partial stop. A cache hit (already recorded from a prior run)
doesn't count against either limit.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.backends.base import DecisionBackend
from app.backends.cache import CachedBackend
from app.backends.claude_backend import ClaudeBackend
from app.backends.jev_backend import JevBackend
from app.backends.types import ClassificationResult, ClassifyInput
from app.core.config import settings as app_settings
from app.eval.classify_metrics import compute_classify_metrics
from app.eval.classify_run import run_classify

REPO_ROOT = Path(__file__).resolve().parents[3]

CLAUDE_TIERS: dict[str, str] = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}

DEFAULT_COST_CEILING_USD = 5.0
DEFAULT_MAX_CALLS = 400


class LiveRunAborted(RuntimeError):
    """Raised the moment a configured ceiling is crossed."""


@dataclass
class LiveRunBudget:
    cost_ceiling_usd: float
    max_calls: int
    calls_made: int = 0
    total_cost_usd: float = 0.0

    def before_call(self) -> None:
        if self.calls_made >= self.max_calls:
            raise LiveRunAborted(
                f"max_calls ({self.max_calls}) reached after {self.calls_made} live calls, "
                f"${self.total_cost_usd:.4f} spent"
            )
        if self.total_cost_usd >= self.cost_ceiling_usd:
            raise LiveRunAborted(
                f"cost_ceiling_usd (${self.cost_ceiling_usd:.2f}) reached after "
                f"{self.calls_made} live calls, ${self.total_cost_usd:.4f} spent"
            )

    def after_call(self, result: ClassificationResult) -> None:
        self.calls_made += 1
        self.total_cost_usd += result.cost_usd


class _BudgetedBackend:
    """Wraps the real backend passed to CachedBackend - only invoked on
    a genuine cache miss, so the budget only ever counts live calls,
    never cache hits."""

    def __init__(self, backend: DecisionBackend, budget: LiveRunBudget) -> None:
        self._backend = backend
        self._budget = budget

    @property
    def name(self) -> str:
        return self._backend.name

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        self._budget.before_call()
        result = self._backend.classify(classify_input)
        self._budget.after_call(result)
        return result


def _record(
    backend: DecisionBackend,
    model: str,
    *,
    mode_name: str,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    cache_root: Path,
    budget: LiveRunBudget,
) -> dict[str, Any]:
    cached = CachedBackend(
        _BudgetedBackend(backend, budget),
        model=model,
        cache_root=cache_root,
        mode="record",
    )
    # fallback=None: every document gets exactly one real call either
    # way (decide() always calls primary once regardless of
    # threshold), so the real app_settings thresholds here make the
    # recorded accepted/escalated split meaningful rather than
    # arbitrary.
    result = run_classify(
        ground_truth,
        fixtures_root,
        mode_name=mode_name,
        primary=cached,
        fallback=None,
        tau_classify=app_settings.tau_classify,
        legible_threshold=app_settings.legible_threshold,
    )
    metrics = compute_classify_metrics(result)
    return {"mode": result.mode, **metrics.model_dump(mode="json")}


def run_live(
    *,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    cache_root: Path,
    cost_ceiling_usd: float,
    max_calls: int,
    claude_only: bool,
    jev_api_key: str | None,
) -> dict[str, Any]:
    budget = LiveRunBudget(cost_ceiling_usd=cost_ceiling_usd, max_calls=max_calls)
    report: dict[str, Any] = {"tiers": {}, "aborted": None}

    try:
        for tier_name, model in CLAUDE_TIERS.items():
            report["tiers"][f"claude-{tier_name}"] = _record(
                ClaudeBackend(model=model),
                model,
                mode_name=f"classify-claude-{tier_name}",
                ground_truth=ground_truth,
                fixtures_root=fixtures_root,
                cache_root=cache_root,
                budget=budget,
            )

        if not claude_only and jev_api_key:
            report["tiers"]["jev"] = _record(
                JevBackend(api_key=jev_api_key, model="jev-1.14.0"),
                "jev-1.14.0",
                mode_name="classify-jev",
                ground_truth=ground_truth,
                fixtures_root=fixtures_root,
                cache_root=cache_root,
                budget=budget,
            )
    except LiveRunAborted as exc:
        report["aborted"] = str(exc)

    report["calls_made"] = budget.calls_made
    report["total_cost_usd"] = budget.total_cost_usd
    return report


def main() -> None:  # pragma: no cover - makes real network calls, not exercised by tests
    load_dotenv(REPO_ROOT / "backend" / ".env")
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-ceiling", type=float, default=DEFAULT_COST_CEILING_USD)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--claude-only", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required (set it in backend/.env)")

    ground_truth_path = REPO_ROOT / "eval" / "fixtures" / "ground_truth.json"
    fixtures_root = REPO_ROOT / "eval" / "fixtures"
    cache_root = REPO_ROOT / "eval" / "fixtures" / "model_cache"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))

    report = run_live(
        ground_truth=ground_truth,
        fixtures_root=fixtures_root,
        cache_root=cache_root,
        cost_ceiling_usd=args.cost_ceiling,
        max_calls=args.max_calls,
        claude_only=args.claude_only,
        jev_api_key=os.environ.get("JEV_API_KEY"),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()

"""Live extract runner (M6): makes REAL calls against Claude over the
license/coi/cv documents in the 12 real packets and records genuine
responses into eval/fixtures/model_cache/, parallel to
app/eval/live_classify.py.

NOT run automatically anywhere - not by pytest, not by CI. This spends
real money and makes real network calls. Invoke explicitly:

    uv run python -m app.eval.live_extract
    uv run python -m app.eval.live_extract --cost-ceiling 2.0 --max-calls 100

Requires ANTHROPIC_API_KEY (backend/.env, loaded via python-dotenv).

Same cost/call ceiling discipline as live_classify.py: every live call
(a genuine cache miss) is checked against a running cost total and
call count *before* it's made; crossing either aborts the run
immediately. A cache hit never counts against either limit.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.backends.claude_extractor import ClaudeExtractor
from app.backends.extract_cache import CachedExtractor, ExtractionBackend
from app.backends.extract_types import ExtractInput, ExtractionResult
from app.eval.extract_metrics import compute_extract_metrics
from app.eval.extract_run import run_extract
from app.eval.extract_vision_run import run_extract_vision
from app.eval.hard_extract_run import load_hard_extraction_cases, run_hard_extract

REPO_ROOT = Path(__file__).resolve().parents[3]

CLAUDE_TIERS: dict[str, str] = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}

DEFAULT_COST_CEILING_USD = 5.0
DEFAULT_MAX_CALLS = 200


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

    def after_call(self, result: ExtractionResult) -> None:
        self.calls_made += 1
        self.total_cost_usd += result.cost_usd


class _BudgetedExtractor:
    def __init__(self, backend: ExtractionBackend, budget: LiveRunBudget) -> None:
        self._backend = backend
        self._budget = budget

    @property
    def name(self) -> str:
        return self._backend.name

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        self._budget.before_call()
        result = self._backend.extract(extract_input)
        self._budget.after_call(result)
        return result


def _cached(
    backend: ExtractionBackend, model: str, *, cache_root: Path, budget: LiveRunBudget
) -> CachedExtractor:
    return CachedExtractor(
        _BudgetedExtractor(backend, budget), model=model, cache_root=cache_root, mode="record"
    )


def _record(
    backend: ExtractionBackend,
    model: str,
    *,
    mode_name: str,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    cache_root: Path,
    budget: LiveRunBudget,
) -> dict[str, Any]:
    cached = _cached(backend, model, cache_root=cache_root, budget=budget)
    result = run_extract(ground_truth, fixtures_root, mode_name=mode_name, backend=cached)
    metrics = compute_extract_metrics(result)
    return {"mode": result.mode, **metrics.model_dump(mode="json")}


def _record_vision(
    backend: ExtractionBackend,
    model: str,
    *,
    mode_name: str,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    cache_root: Path,
    budget: LiveRunBudget,
) -> dict[str, Any]:
    cached = _cached(backend, model, cache_root=cache_root, budget=budget)
    result = run_extract_vision(ground_truth, fixtures_root, mode_name=mode_name, backend=cached)
    metrics = compute_extract_metrics(result)
    return {"mode": result.mode, **metrics.model_dump(mode="json")}


def _record_hard(
    backend: ExtractionBackend,
    model: str,
    *,
    mode_name: str,
    hard_cases: list[dict[str, Any]],
    hard_fixtures_root: Path,
    cache_root: Path,
    budget: LiveRunBudget,
) -> dict[str, Any]:
    cached = _cached(backend, model, cache_root=cache_root, budget=budget)
    result = run_hard_extract(
        hard_cases, hard_fixtures_root, mode_name=mode_name, backend=cached
    )
    metrics = compute_extract_metrics(result)
    return {"mode": result.mode, **metrics.model_dump(mode="json")}


def run_live(
    *,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    cache_root: Path,
    cost_ceiling_usd: float,
    max_calls: int,
    with_vision: bool = False,
    hard_cases: list[dict[str, Any]] | None = None,
    hard_fixtures_root: Path | None = None,
) -> dict[str, Any]:
    budget = LiveRunBudget(cost_ceiling_usd=cost_ceiling_usd, max_calls=max_calls)
    report: dict[str, Any] = {"tiers": {}, "aborted": None}

    try:
        for tier_name, model in CLAUDE_TIERS.items():
            report["tiers"][f"claude-{tier_name}"] = _record(
                ClaudeExtractor(model=model),
                model,
                mode_name=f"extract-claude-{tier_name}",
                ground_truth=ground_truth,
                fixtures_root=fixtures_root,
                cache_root=cache_root,
                budget=budget,
            )
        if with_vision:
            for tier_name, model in CLAUDE_TIERS.items():
                report["tiers"][f"claude-{tier_name}-vision"] = _record_vision(
                    ClaudeExtractor(model=model),
                    model,
                    mode_name=f"extract-claude-{tier_name}-vision",
                    ground_truth=ground_truth,
                    fixtures_root=fixtures_root,
                    cache_root=cache_root,
                    budget=budget,
                )
        if hard_cases is not None:
            assert hard_fixtures_root is not None
            for tier_name, model in CLAUDE_TIERS.items():
                report["tiers"][f"claude-{tier_name}-hard"] = _record_hard(
                    ClaudeExtractor(model=model),
                    model,
                    mode_name=f"extract-claude-{tier_name}-hard",
                    hard_cases=hard_cases,
                    hard_fixtures_root=hard_fixtures_root,
                    cache_root=cache_root,
                    budget=budget,
                )
    except LiveRunAborted as exc:
        report["aborted"] = str(exc)

    report["calls_made"] = budget.calls_made
    report["total_cost_usd"] = budget.total_cost_usd
    return report


def main() -> None:  # pragma: no cover - makes real network calls, not exercised by tests
    import os

    load_dotenv(REPO_ROOT / "backend" / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-ceiling", type=float, default=DEFAULT_COST_CEILING_USD)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument(
        "--with-vision",
        action="store_true",
        help=(
            "Also run the two image-only license scans "
            "(app/eval/extract_vision_run.py) through each tier."
        ),
    )
    parser.add_argument(
        "--with-hard",
        action="store_true",
        help=(
            "Also run the hard extraction set (app/eval/generator/"
            "hard_extraction_set.py, n=30) through each tier."
        ),
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required (set it in backend/.env)")

    ground_truth_path = REPO_ROOT / "eval" / "fixtures" / "ground_truth.json"
    fixtures_root = REPO_ROOT / "eval" / "fixtures"
    cache_root = REPO_ROOT / "eval" / "fixtures" / "model_cache"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))

    hard_cases = None
    hard_fixtures_root = None
    if args.with_hard:
        hard_fixtures_root = REPO_ROOT / "eval" / "fixtures"
        hard_path = hard_fixtures_root / "hard_extraction_ground_truth.json"
        hard_cases = load_hard_extraction_cases(hard_path)

    report = run_live(
        ground_truth=ground_truth,
        fixtures_root=fixtures_root,
        cache_root=cache_root,
        cost_ceiling_usd=args.cost_ceiling,
        max_calls=args.max_calls,
        with_vision=args.with_vision,
        hard_cases=hard_cases,
        hard_fixtures_root=hard_fixtures_root,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()

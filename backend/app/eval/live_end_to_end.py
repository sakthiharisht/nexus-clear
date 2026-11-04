"""Live end-to-end runner (M7 #6): makes REAL calls against Claude for
both Extract and Reconcile/Investigator across all 12 real packets and
records genuine responses into eval/fixtures/model_cache/, parallel to
app/eval/live_extract.py.

NOT run automatically anywhere - not by pytest, not by CI. Invoke
explicitly:

    uv run python -m app.eval.live_end_to_end
    uv run python -m app.eval.live_end_to_end --cost-ceiling 2.0 --max-calls 100

Requires ANTHROPIC_API_KEY. One shared budget across both extraction
calls and investigation calls (an investigation is itself 2+ model
turns) - same cost-ceiling/max-calls discipline as every other live
runner in this project.
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
from app.eval.end_to_end_run import run_end_to_end
from app.reconcile.cache import CachedInvestigator
from app.reconcile.investigator import (
    InvestigationResult,
    Investigator,
    InvestigatorLike,
    NameMatchTask,
    RegistryTask,
)
from app.rules.loader import load_rule_pack
from app.tools_mcp.server import build_mcp_server

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_COST_CEILING_USD = 5.0
DEFAULT_MAX_CALLS = 200
_MODEL = "claude-haiku-5-5"


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

    def after_cost(self, cost_usd: float) -> None:
        self.calls_made += 1
        self.total_cost_usd += cost_usd


class _BudgetedExtractor:
    def __init__(self, backend: ExtractionBackend, budget: LiveRunBudget) -> None:
        self._backend = backend
        self._budget = budget

    @property
    def name(self) -> str:
        return self._backend.name

    @property
    def prompt_version(self) -> str:
        return self._backend.prompt_version

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        self._budget.before_call()
        result = self._backend.extract(extract_input)
        self._budget.after_cost(result.cost_usd)
        return result


class _BudgetedInvestigator:
    def __init__(self, investigator: InvestigatorLike, budget: LiveRunBudget) -> None:
        self._investigator = investigator
        self._budget = budget

    @property
    def prompt_version(self) -> str:
        return self._investigator.prompt_version

    def investigate(
        self, *, name_match_tasks: list[NameMatchTask], registry_tasks: list[RegistryTask]
    ) -> InvestigationResult:
        self._budget.before_call()
        result = self._investigator.investigate(
            name_match_tasks=name_match_tasks, registry_tasks=registry_tasks
        )
        self._budget.after_cost(result.cost_usd)
        return result


def run_live(
    *,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    rule_pack_path: Path,
    registry_fixtures_root: Path,
    leie_cache_path: Path,
    cache_root: Path,
    cost_ceiling_usd: float,
    max_calls: int,
) -> dict[str, Any]:
    pack = load_rule_pack(rule_pack_path)
    budget = LiveRunBudget(cost_ceiling_usd=cost_ceiling_usd, max_calls=max_calls)

    extractor = CachedExtractor(
        _BudgetedExtractor(ClaudeExtractor(model=_MODEL), budget),
        model=_MODEL,
        cache_root=cache_root,
        mode="record",
    )
    mcp = build_mcp_server(
        mode="fixture",
        fixtures_root=registry_fixtures_root,
        rule_pack_path=rule_pack_path,
        leie_cache_path=leie_cache_path,
    )
    raw_investigator = Investigator(mcp, model=_MODEL, max_tool_calls=6)
    investigator = CachedInvestigator(
        _BudgetedInvestigator(raw_investigator, budget),
        model=_MODEL,
        cache_root=cache_root,
        mode="record",
    )

    report: dict[str, Any] = {"aborted": None}
    try:
        result = run_end_to_end(
            pack,
            ground_truth,
            fixtures_root,
            mode_name="end_to_end",
            extractor=extractor,
            investigator=investigator,
        )
        report["packets_run"] = len(result.packets)
    except LiveRunAborted as exc:
        report["aborted"] = str(exc)
        report["packets_run"] = None

    report["calls_made"] = budget.calls_made
    report["total_cost_usd"] = budget.total_cost_usd
    return report


def main() -> None:  # pragma: no cover - makes real network calls, not exercised by tests
    import os

    load_dotenv(REPO_ROOT / "backend" / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-ceiling", type=float, default=DEFAULT_COST_CEILING_USD)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required (set it in backend/.env)")

    fixtures_root = REPO_ROOT / "eval" / "fixtures"
    ground_truth = json.loads(
        (fixtures_root / "ground_truth.json").read_text(encoding="utf-8")
    )

    report = run_live(
        ground_truth=ground_truth,
        fixtures_root=fixtures_root,
        rule_pack_path=REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml",
        registry_fixtures_root=fixtures_root / "registry",
        leie_cache_path=REPO_ROOT / "data" / "cache" / "leie_updated.csv",
        cache_root=fixtures_root / "model_cache",
        cost_ceiling_usd=args.cost_ceiling,
        max_calls=args.max_calls,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()

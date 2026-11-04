"""Unit tests for app.eval.live_extract's budget/abort mechanism and
run_live's wiring - all against fake backends, never a real network
call. See tests/backends/test_d14_injection_immunity.py for the one
opt-in test in this milestone that does make real calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.extract_types import CvExtraction, ExtractInput, ExtractionResult
from app.eval.live_extract import LiveRunAborted, LiveRunBudget, _BudgetedExtractor, run_live


class _FakeExtractor:
    prompt_version = "test"

    def __init__(self, name: str, cost_usd: float = 0.01) -> None:
        self.name = name
        self.calls = 0
        self._cost_usd = cost_usd

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        self.calls += 1
        return ExtractionResult(
            kind="cv", fields=CvExtraction(), cost_usd=self._cost_usd, decided_by="claude"
        )


def _input() -> ExtractInput:
    return ExtractInput(doc_id="doc-cv", kind="cv", filename="p1/cv.pdf", document_text="cv text")


def test_budget_allows_calls_under_both_ceilings() -> None:
    budget = LiveRunBudget(cost_ceiling_usd=1.0, max_calls=10)
    backend = _BudgetedExtractor(_FakeExtractor("claude", cost_usd=0.1), budget)
    for _ in range(5):
        backend.extract(_input())
    assert budget.calls_made == 5
    assert budget.total_cost_usd == pytest.approx(0.5)


def test_budget_aborts_on_max_calls() -> None:
    budget = LiveRunBudget(cost_ceiling_usd=100.0, max_calls=2)
    backend = _BudgetedExtractor(_FakeExtractor("claude", cost_usd=0.01), budget)
    backend.extract(_input())
    backend.extract(_input())
    with pytest.raises(LiveRunAborted, match="max_calls"):
        backend.extract(_input())


def test_budget_aborts_on_cost_ceiling() -> None:
    budget = LiveRunBudget(cost_ceiling_usd=0.05, max_calls=1000)
    backend = _BudgetedExtractor(_FakeExtractor("claude", cost_usd=0.03), budget)
    backend.extract(_input())  # $0.03, under ceiling
    backend.extract(_input())  # $0.06, now over
    with pytest.raises(LiveRunAborted, match="cost_ceiling_usd"):
        backend.extract(_input())


def test_a_cache_hit_never_counts_against_the_budget(tmp_path: Path) -> None:
    from app.backends.extract_cache import CachedExtractor

    budget = LiveRunBudget(cost_ceiling_usd=1.0, max_calls=1)
    fake = _FakeExtractor("claude", cost_usd=0.01)
    cached = CachedExtractor(
        _BudgetedExtractor(fake, budget), model="m", cache_root=tmp_path, mode="record"
    )
    cached.extract(_input())  # 1 live call - exhausts max_calls=1
    assert budget.calls_made == 1

    cached.extract(_input())  # same input: cache hit, must not touch the budget
    assert budget.calls_made == 1
    assert fake.calls == 1


def _one_document_ground_truth() -> dict[str, object]:
    return {
        "packets": [
            {
                "packet_id": "p1",
                "documents": {"cv": "packets/p1/cv.pdf"},
                "facts": {
                    "cv": {"positions": []},
                    "documents": [
                        {
                            "slot": "cv",
                            "expected_doc_type": "cv",
                            "uploaded_doc_type": "cv",
                            "legible_score": 0.9,
                        }
                    ],
                },
            }
        ]
    }


def test_run_live_aborts_mid_run_and_reports_which_tiers_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class _RecordingFake:
        prompt_version = "test"

        def __init__(self, model: str) -> None:
            self.name = "claude"
            self._model = model

        def extract(self, extract_input: ExtractInput) -> ExtractionResult:
            calls.append(self._model)
            return ExtractionResult(
                kind="cv", fields=CvExtraction(), cost_usd=0.01, decided_by="claude"
            )

    monkeypatch.setattr(
        "app.eval.live_extract.ClaudeExtractor", lambda model: _RecordingFake(model)
    )

    report = run_live(
        ground_truth=_one_document_ground_truth(),
        fixtures_root=tmp_path,
        cache_root=tmp_path / "cache",
        cost_ceiling_usd=100.0,
        max_calls=1,  # exactly one live call allowed, total
    )

    assert report["calls_made"] == 1
    assert report["aborted"] is not None
    assert "max_calls" in report["aborted"]
    assert len(report["tiers"]) == 1  # only the first tier got to run

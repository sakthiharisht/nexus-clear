"""Unit tests for app.eval.live_classify's budget/abort mechanism and
run_live's wiring - all against fake backends, never a real network
call. See tests/backends/test_live_smoke.py for the opt-in tests that
do make real calls, skipped whenever API keys are absent (including in
CI, which has none).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.types import ClassificationResult, ClassifyInput
from app.eval.live_classify import LiveRunAborted, LiveRunBudget, _BudgetedBackend, run_live


class _FakeBackend:
    prompt_version = "test"

    def __init__(self, name: str, cost_usd: float = 0.01) -> None:
        self.name = name
        self.calls = 0
        self._cost_usd = cost_usd

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        self.calls += 1
        return ClassificationResult(
            doc_type="cv",
            probabilities={"cv": 0.95},
            legible=0.95,
            slot_match=True,
            decided_by="claude",
            cost_usd=self._cost_usd,
            input_tokens=100,
            output_tokens=20,
        )


def _input() -> ClassifyInput:
    return ClassifyInput(slot="cv", filename="p1/cv.pdf", allowed_doc_types=["cv", "other"])


def test_budget_allows_calls_under_both_ceilings() -> None:
    budget = LiveRunBudget(cost_ceiling_usd=1.0, max_calls=10)
    backend = _BudgetedBackend(_FakeBackend("claude", cost_usd=0.1), budget)
    for _ in range(5):
        backend.classify(_input())
    assert budget.calls_made == 5
    assert budget.total_cost_usd == pytest.approx(0.5)


def test_budget_aborts_on_max_calls() -> None:
    budget = LiveRunBudget(cost_ceiling_usd=100.0, max_calls=2)
    backend = _BudgetedBackend(_FakeBackend("claude", cost_usd=0.01), budget)
    backend.classify(_input())
    backend.classify(_input())
    with pytest.raises(LiveRunAborted, match="max_calls"):
        backend.classify(_input())


def test_budget_aborts_on_cost_ceiling() -> None:
    budget = LiveRunBudget(cost_ceiling_usd=0.05, max_calls=1000)
    backend = _BudgetedBackend(_FakeBackend("claude", cost_usd=0.03), budget)
    backend.classify(_input())  # $0.03, under ceiling
    backend.classify(_input())  # $0.06, now over
    with pytest.raises(LiveRunAborted, match="cost_ceiling_usd"):
        backend.classify(_input())


def test_a_cache_hit_never_counts_against_the_budget(tmp_path: Path) -> None:
    from app.backends.cache import CachedBackend

    budget = LiveRunBudget(cost_ceiling_usd=1.0, max_calls=1)
    fake = _FakeBackend("claude", cost_usd=0.01)
    cached = CachedBackend(
        _BudgetedBackend(fake, budget), model="m", cache_root=tmp_path, mode="record"
    )
    cached.classify(_input())  # 1 live call - exhausts max_calls=1
    assert budget.calls_made == 1

    # Same input again: a cache hit, must NOT touch the budget or the
    # backend, and must NOT raise even though max_calls is already spent.
    cached.classify(_input())
    assert budget.calls_made == 1
    assert fake.calls == 1


def _one_document_ground_truth() -> dict[str, object]:
    return {
        "packets": [
            {
                "packet_id": "p1",
                "documents": {"cv": "packets/p1/cv.pdf"},
                "facts": {
                    "documents": [
                        {
                            "slot": "cv",
                            "expected_doc_type": "cv",
                            "uploaded_doc_type": "cv",
                            "legible_score": 0.9,
                        }
                    ]
                },
            }
        ]
    }


def test_run_live_aborts_mid_run_and_reports_which_tiers_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ceiling tight enough to allow exactly one tier's one document
    through, then abort on the second tier - confirms the abort is
    recorded, not swallowed, and doesn't crash the whole process."""
    calls: list[str] = []

    class _RecordingFake:
        prompt_version = "test"

        def __init__(self, name: str, model: str) -> None:
            self.name = name
            self._model = model

        def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
            calls.append(self._model)
            return ClassificationResult(
                doc_type="cv",
                probabilities={"cv": 0.95},
                legible=0.95,
                slot_match=True,
                decided_by="claude",
                cost_usd=0.01,
                input_tokens=100,
                output_tokens=20,
            )

    monkeypatch.setattr(
        "app.eval.live_classify.ClaudeBackend",
        lambda model: _RecordingFake("claude", model),
    )

    report = run_live(
        ground_truth=_one_document_ground_truth(),
        fixtures_root=tmp_path,
        cache_root=tmp_path / "cache",
        cost_ceiling_usd=100.0,
        max_calls=1,  # exactly one live call allowed, total
        claude_only=True,
        jev_api_key=None,
    )

    assert report["calls_made"] == 1
    assert report["aborted"] is not None
    assert "max_calls" in report["aborted"]
    assert len(report["tiers"]) == 1  # only the first tier got to run


def test_run_live_records_jev_when_a_key_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeClaude:
        prompt_version = "test"

        def __init__(self, model: str) -> None:
            self.name = "claude"

        def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
            return ClassificationResult(
                doc_type="cv", probabilities={"cv": 0.95}, legible=0.95, slot_match=True,
                decided_by="claude", cost_usd=0.01, input_tokens=100, output_tokens=20,
            )

    class _FakeJev:
        prompt_version = "test"

        def __init__(self, api_key: str, model: str) -> None:
            self.name = "jev"

        def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
            return ClassificationResult(
                doc_type="cv", probabilities={"cv": 0.9}, legible=0.9, slot_match=True,
                decided_by="jev", cost_usd=0.0, input_tokens=300, output_tokens=15,
            )

    monkeypatch.setattr("app.eval.live_classify.ClaudeBackend", _FakeClaude)
    monkeypatch.setattr("app.eval.live_classify.JevBackend", _FakeJev)

    report = run_live(
        ground_truth=_one_document_ground_truth(),
        fixtures_root=tmp_path,
        cache_root=tmp_path / "cache",
        cost_ceiling_usd=100.0,
        max_calls=100,
        claude_only=False,
        jev_api_key="test-key",
    )

    assert report["aborted"] is None
    assert "jev" in report["tiers"]
    assert report["tiers"]["jev"]["n"] == 1

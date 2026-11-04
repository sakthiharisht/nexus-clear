from __future__ import annotations

from app.backends.pricing import estimate_cost_usd


def test_estimate_cost_usd_uses_the_pinned_models_rate() -> None:
    cost = estimate_cost_usd("claude-haiku-5-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.10 + 0.50


def test_estimate_cost_usd_is_zero_for_an_unpinned_model() -> None:
    assert estimate_cost_usd("some-unknown-model", input_tokens=1000, output_tokens=1000) == 0.0

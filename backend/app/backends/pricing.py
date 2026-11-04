"""Shared Claude pricing table (verified 2026-11-04 against
platform.claude.com/docs/en/about-claude/pricing - see
app/backends/claude_backend.py's module docstring for the full
verification note). One table for every stage that calls a pinned
Claude model (Classify, Extract) so a price update can't drift between
callers.
"""

from __future__ import annotations

# USD per million tokens, input/output.
PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = PRICING_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

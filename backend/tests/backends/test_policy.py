from __future__ import annotations

from app.backends.policy import decide
from app.backends.types import ClassificationResult, ClassifyInput

_TAU = 0.85
_LEGIBLE = 0.7


class _StubBackend:
    prompt_version = "test"

    def __init__(self, name: str, result: ClassificationResult) -> None:
        self.name = name
        self._result = result
        self.calls = 0

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        self.calls += 1
        return self._result


def _result(
    doc_type: str, probability: float, legible: float, decided_by: str
) -> ClassificationResult:
    return ClassificationResult(
        doc_type=doc_type,
        probabilities={doc_type: probability},
        legible=legible,
        slot_match=True,
        decided_by=decided_by,  # type: ignore[arg-type]
    )


def _input() -> ClassifyInput:
    return ClassifyInput(slot="license", filename="x.pdf", allowed_doc_types=["texas_lpc_license"])


def test_primary_above_threshold_is_accepted_without_touching_fallback() -> None:
    primary = _StubBackend("jev", _result("texas_lpc_license", 0.95, 0.9, "jev"))
    fallback = _StubBackend("claude", _result("texas_lpc_license", 0.99, 0.99, "claude"))

    decision = decide(
        _input(), primary=primary, fallback=fallback, tau_classify=_TAU, legible_threshold=_LEGIBLE
    )

    assert decision.accepted is True
    assert decision.escalated is False
    assert decision.result.decided_by == "jev"
    assert fallback.calls == 0


def test_primary_below_threshold_falls_back_and_fallback_accepted() -> None:
    primary = _StubBackend("jev", _result("texas_lpc_license", 0.5, 0.9, "jev"))
    fallback = _StubBackend("claude", _result("texas_lpc_license", 0.95, 0.95, "claude"))

    decision = decide(
        _input(), primary=primary, fallback=fallback, tau_classify=_TAU, legible_threshold=_LEGIBLE
    )

    assert decision.accepted is True
    assert decision.escalated is False
    assert decision.result.decided_by == "claude"
    assert fallback.calls == 1


def test_both_below_threshold_escalates() -> None:
    primary = _StubBackend("jev", _result("texas_lpc_license", 0.5, 0.9, "jev"))
    fallback = _StubBackend("claude", _result("texas_lpc_license", 0.6, 0.9, "claude"))

    decision = decide(
        _input(), primary=primary, fallback=fallback, tau_classify=_TAU, legible_threshold=_LEGIBLE
    )

    assert decision.accepted is False
    assert decision.escalated is True
    assert decision.reason is not None and "jev" in decision.reason and "claude" in decision.reason


def test_low_legibility_escalates_even_with_high_probability() -> None:
    primary = _StubBackend("claude", _result("texas_lpc_license", 0.99, 0.2, "claude"))

    decision = decide(
        _input(), primary=primary, fallback=None, tau_classify=_TAU, legible_threshold=_LEGIBLE
    )

    assert decision.accepted is False
    assert decision.escalated is True


def test_decision_backend_claude_with_no_fallback_configured_escalates_directly() -> None:
    """CLAUDE.md invariant 6: DECISION_BACKEND=claude must run end to
    end - this is the no-Jev-at-all shape, confirming a below-threshold
    Claude result escalates without needing any fallback backend."""
    primary = _StubBackend("claude", _result("texas_lpc_license", 0.4, 0.9, "claude"))

    decision = decide(
        _input(), primary=primary, fallback=None, tau_classify=_TAU, legible_threshold=_LEGIBLE
    )

    assert decision.accepted is False
    assert decision.escalated is True
    assert decision.reason is not None and "no fallback configured" in decision.reason


def test_decision_backend_claude_above_threshold_accepts_with_no_fallback_involvement() -> None:
    primary = _StubBackend("claude", _result("texas_lpc_license", 0.95, 0.95, "claude"))

    decision = decide(
        _input(), primary=primary, fallback=None, tau_classify=_TAU, legible_threshold=_LEGIBLE
    )

    assert decision.accepted is True
    assert decision.result.decided_by == "claude"

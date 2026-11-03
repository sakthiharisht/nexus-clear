"""Classify policy (SPEC.md section 7.2): "accept if doc_type
probability >= TAU_CLASSIFY (default 0.85, tune from eval) and legible
>= 0.7. Otherwise fall back to Claude (cheap tier). If still low, ask
the provider to re-upload or escalate."

`primary` is Jev when DECISION_BACKEND=jev, Claude when
DECISION_BACKEND=claude - see app/backends/factory.py. Passing
`fallback=None` is how CLAUDE.md invariant 6 ("DECISION_BACKEND=claude
must run end to end") holds with zero Jev involvement: there's simply
nothing to fall back to, so a below-threshold Claude result escalates
directly.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.backends.base import DecisionBackend
from app.backends.types import ClassificationResult, ClassifyInput


class ClassifyDecision(BaseModel):
    result: ClassificationResult
    accepted: bool
    escalated: bool
    reason: str | None = None


def _passes_threshold(
    result: ClassificationResult, *, tau_classify: float, legible_threshold: float
) -> bool:
    top_probability = max(result.probabilities.values()) if result.probabilities else 0.0
    return top_probability >= tau_classify and result.legible >= legible_threshold


def decide(
    classify_input: ClassifyInput,
    *,
    primary: DecisionBackend,
    fallback: DecisionBackend | None,
    tau_classify: float,
    legible_threshold: float,
) -> ClassifyDecision:
    result = primary.classify(classify_input)
    if _passes_threshold(result, tau_classify=tau_classify, legible_threshold=legible_threshold):
        return ClassifyDecision(result=result, accepted=True, escalated=False)

    if fallback is None:
        return ClassifyDecision(
            result=result,
            accepted=False,
            escalated=True,
            reason=f"{primary.name} below threshold, no fallback configured",
        )

    fallback_result = fallback.classify(classify_input)
    if _passes_threshold(
        fallback_result, tau_classify=tau_classify, legible_threshold=legible_threshold
    ):
        return ClassifyDecision(result=fallback_result, accepted=True, escalated=False)

    return ClassifyDecision(
        result=fallback_result,
        accepted=False,
        escalated=True,
        reason=f"{primary.name} and {fallback.name} both below threshold",
    )

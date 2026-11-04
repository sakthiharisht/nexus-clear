"""Accuracy, calibration (ECE), escalation rate, cost, and latency for
a ClassifyModeResult (SPEC.md section 14's M5 accept criterion).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.eval.classify_types import ClassifyModeResult

_ECE_BINS = 10


class ClassifyMetrics(BaseModel):
    n: int
    # Over ACCEPTED (non-escalated) documents only - the honest
    # end-to-end number: escalated documents never become an automatic
    # doc_type decision, so they're excluded here the same way the M3
    # baseline's accuracy_when_decided excludes undecided findings.
    accuracy: float
    # Expected Calibration Error, over ALL documents including
    # escalated ones - calibration asks "when the model reported X%
    # confidence, was it right X% of the time," which is a property of
    # every prediction the model made, not just the accepted ones.
    ece: float
    escalation_rate: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    # False whenever any document's cost is a placeholder rather than
    # a measured/priced value (currently: every Jev result - its
    # direct-API pricing isn't verified). Report rendering shows "n/a"
    # for the whole mode rather than a misleadingly precise total, the
    # same way `simulated` taints a whole mode's label.
    cost_known: bool
    mean_latency_ms: float


def compute_classify_metrics(result: ClassifyModeResult) -> ClassifyMetrics:
    documents = result.documents
    n = len(documents)
    if n == 0:
        return ClassifyMetrics(
            n=0,
            accuracy=0.0,
            ece=0.0,
            escalation_rate=0.0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            cost_known=True,
            mean_latency_ms=0.0,
        )

    accepted = [d for d in documents if not d.escalated]
    accuracy = (
        sum(1 for d in accepted if d.predicted_doc_type == d.true_doc_type) / len(accepted)
        if accepted
        else 0.0
    )

    bins: list[list[tuple[float, bool]]] = [[] for _ in range(_ECE_BINS)]
    for d in documents:
        correct = d.predicted_doc_type == d.true_doc_type
        bin_index = min(int(d.predicted_probability * _ECE_BINS), _ECE_BINS - 1)
        bins[bin_index].append((d.predicted_probability, correct))

    ece = 0.0
    for bin_items in bins:
        if not bin_items:
            continue
        bin_confidence = sum(p for p, _ in bin_items) / len(bin_items)
        bin_accuracy = sum(1 for _, correct in bin_items if correct) / len(bin_items)
        ece += (len(bin_items) / n) * abs(bin_confidence - bin_accuracy)

    escalated_count = sum(1 for d in documents if d.escalated)
    return ClassifyMetrics(
        n=n,
        accuracy=accuracy,
        ece=ece,
        escalation_rate=escalated_count / n,
        total_input_tokens=sum(d.input_tokens for d in documents),
        total_output_tokens=sum(d.output_tokens for d in documents),
        total_cost_usd=sum(d.cost_usd for d in documents),
        cost_known=all(d.cost_known for d in documents),
        mean_latency_ms=sum(d.latency_ms for d in documents) / n,
    )

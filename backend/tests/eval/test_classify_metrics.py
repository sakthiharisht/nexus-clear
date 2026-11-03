from __future__ import annotations

from app.eval.classify_metrics import compute_classify_metrics
from app.eval.classify_types import ClassifyModeResult, DocumentClassification


def _doc(
    *,
    predicted_doc_type: str = "cv",
    true_doc_type: str = "cv",
    predicted_probability: float = 0.95,
    accepted: bool = True,
    escalated: bool = False,
    cost_usd: float = 0.001,
    latency_ms: float = 100.0,
    simulated: bool = False,
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> DocumentClassification:
    return DocumentClassification(
        packet_id="p1",
        slot="cv",
        expected_doc_type="cv",
        true_doc_type=true_doc_type,
        predicted_doc_type=predicted_doc_type,
        predicted_probability=predicted_probability,
        predicted_legible=0.9,
        predicted_slot_match=True,
        accepted=accepted,
        escalated=escalated,
        decided_by="claude",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        simulated=simulated,
    )


def test_empty_result_has_zeroed_metrics() -> None:
    metrics = compute_classify_metrics(ClassifyModeResult(mode="x", documents=[]))
    assert metrics.n == 0
    assert metrics.accuracy == 0.0
    assert metrics.ece == 0.0
    assert metrics.escalation_rate == 0.0


def test_accuracy_is_one_when_every_accepted_prediction_is_correct() -> None:
    result = ClassifyModeResult(
        mode="x", documents=[_doc(), _doc(predicted_doc_type="w9", true_doc_type="w9")]
    )
    metrics = compute_classify_metrics(result)
    assert metrics.accuracy == 1.0


def test_accuracy_excludes_escalated_documents() -> None:
    result = ClassifyModeResult(
        mode="x",
        documents=[
            _doc(),  # accepted, correct
            _doc(predicted_doc_type="other", true_doc_type="cv", escalated=True, accepted=False),
        ],
    )
    metrics = compute_classify_metrics(result)
    # If the escalated (wrong) document counted, accuracy would be 0.5.
    assert metrics.accuracy == 1.0
    assert metrics.escalation_rate == 0.5


def test_ece_is_zero_for_perfectly_calibrated_predictions() -> None:
    # 10 documents, each predicted at 1.0 confidence, all correct -> ECE 0.
    documents = [_doc(predicted_probability=1.0) for _ in range(10)]
    metrics = compute_classify_metrics(ClassifyModeResult(mode="x", documents=documents))
    assert metrics.ece == 0.0


def test_ece_is_positive_for_overconfident_wrong_predictions() -> None:
    documents = [
        _doc(predicted_probability=0.99, predicted_doc_type="other", true_doc_type="cv")
        for _ in range(5)
    ]
    metrics = compute_classify_metrics(ClassifyModeResult(mode="x", documents=documents))
    assert metrics.ece > 0.9  # ~100% confident, 0% correct


def test_total_cost_and_mean_latency_are_summed_and_averaged() -> None:
    documents = [
        _doc(cost_usd=0.01, latency_ms=100.0),
        _doc(cost_usd=0.02, latency_ms=300.0),
    ]
    metrics = compute_classify_metrics(ClassifyModeResult(mode="x", documents=documents))
    assert metrics.total_cost_usd == 0.03
    assert metrics.mean_latency_ms == 200.0


def test_total_tokens_are_summed_across_documents() -> None:
    documents = [
        _doc(input_tokens=300, output_tokens=40),
        _doc(input_tokens=500, output_tokens=60),
    ]
    metrics = compute_classify_metrics(ClassifyModeResult(mode="x", documents=documents))
    assert metrics.total_input_tokens == 800
    assert metrics.total_output_tokens == 100

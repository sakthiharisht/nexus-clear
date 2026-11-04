from __future__ import annotations

from app.eval.extract_metrics import compute_extract_metrics
from app.eval.extract_types import DocumentExtraction, ExtractModeResult, FieldResult


def _doc(field_results: list[FieldResult], **overrides: object) -> DocumentExtraction:
    base = {
        "packet_id": "p1",
        "slot": "license",
        "kind": "license",
        "decided_by": "claude",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.01,
        "cost_known": True,
        "latency_ms": 500.0,
        "simulated": False,
        "field_results": field_results,
    }
    base.update(overrides)
    return DocumentExtraction.model_validate(base)


def test_compute_extract_metrics_on_empty_result() -> None:
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[]))
    assert metrics.n_documents == 0
    assert metrics.overall_coverage == 1.0
    assert metrics.overall_accuracy_when_known == 1.0


def test_coverage_and_accuracy_split_known_but_wrong_from_unknown() -> None:
    doc = _doc(
        [
            FieldResult(
                field="license.holder_name",
                expected="Jane Doe",
                predicted="Jane Doe",
                status="known",
                quote_verified=True,
                correct=True,
            )
        ]
    )
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc]))
    field_metrics = metrics.per_field["license.holder_name"]
    assert field_metrics.n_decidable == 1
    assert field_metrics.coverage == 1.0
    assert field_metrics.accuracy_when_known == 1.0


def test_a_known_but_wrong_field_lowers_accuracy_not_coverage() -> None:
    doc = _doc(
        [
            FieldResult(
                field="license.holder_name",
                expected="Jane Doe",
                predicted="John Smith",
                status="known",
                quote_verified=True,
                correct=False,
            )
        ]
    )
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc]))
    field_metrics = metrics.per_field["license.holder_name"]
    assert field_metrics.coverage == 1.0
    assert field_metrics.accuracy_when_known == 0.0


def test_an_unknown_field_lowers_coverage_and_does_not_count_against_accuracy() -> None:
    doc = _doc(
        [
            FieldResult(
                field="license.holder_name",
                expected="Jane Doe",
                predicted=None,
                status="unknown",
                quote_verified=False,
                correct=False,
            )
        ]
    )
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc]))
    field_metrics = metrics.per_field["license.holder_name"]
    assert field_metrics.coverage == 0.0
    # No known predictions at all - accuracy_when_known defaults to 1.0
    # (vacuously true), the same convention M3's accuracy_when_decided uses.
    assert field_metrics.accuracy_when_known == 1.0


def test_a_field_with_no_ground_truth_value_is_not_decidable() -> None:
    doc = _doc(
        [
            FieldResult(
                field="coi.aggregate",
                expected=None,
                predicted=None,
                status="unknown",
                quote_verified=False,
                correct=True,
            )
        ]
    )
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc]))
    field_metrics = metrics.per_field["coi.aggregate"]
    assert field_metrics.n_decidable == 0
    assert field_metrics.coverage == 1.0


def test_quote_verified_rate_only_counts_known_fields() -> None:
    doc = _doc(
        [
            FieldResult(
                field="license.holder_name",
                expected="Jane Doe",
                predicted="Jane Doe",
                status="known",
                quote_verified=True,
                correct=True,
            ),
            FieldResult(
                field="license.license_number",
                expected=None,
                predicted=None,
                status="unknown",
                quote_verified=False,
                correct=True,
            ),
        ]
    )
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc]))
    assert metrics.quote_verified_rate == 1.0


def test_cost_and_latency_are_aggregated_across_documents() -> None:
    doc1 = _doc([], cost_usd=0.01, latency_ms=100.0)
    doc2 = _doc([], cost_usd=0.02, latency_ms=300.0)
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc1, doc2]))
    assert metrics.total_cost_usd == 0.03
    assert metrics.mean_latency_ms == 200.0


def test_cost_known_false_when_any_document_has_unknown_cost() -> None:
    doc1 = _doc([], cost_known=True)
    doc2 = _doc([], cost_known=False)
    metrics = compute_extract_metrics(ExtractModeResult(mode="m", documents=[doc1, doc2]))
    assert metrics.cost_known is False

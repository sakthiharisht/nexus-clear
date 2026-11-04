"""Field-level accuracy/coverage for an ExtractModeResult (SPEC.md
section 14, M6). "Coverage" and "accuracy_when_known" mirror
app/eval/metrics.py's M3 coverage/accuracy_when_decided split: coverage
asks how often a field that genuinely has a ground-truth value gets
extracted at all (status == "known"); accuracy_when_known asks, of
those, how often the value is actually right. Keeping them separate
means a model that's honestly cautious (low coverage, high accuracy)
doesn't get scored the same as one that's confidently wrong.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from app.eval.extract_types import ExtractModeResult


class ExtractFieldMetrics(BaseModel):
    field: str
    # Documents where ground truth has a real (non-None) value for
    # this field - the denominator for both rates below.
    n_decidable: int
    coverage: float
    accuracy_when_known: float


class ExtractMetrics(BaseModel):
    mode: str
    n_documents: int
    per_field: dict[str, ExtractFieldMetrics]
    overall_coverage: float
    overall_accuracy_when_known: float
    quote_verified_rate: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    cost_known: bool
    mean_latency_ms: float


def compute_extract_metrics(result: ExtractModeResult) -> ExtractMetrics:
    documents = result.documents
    n_documents = len(documents)

    by_field: dict[str, list[tuple[bool, bool, bool, bool]]] = defaultdict(list)
    # Each tuple: (decidable, known, correct, quote_verified)
    for doc in documents:
        for fr in doc.field_results:
            decidable = fr.expected is not None
            known = fr.status == "known"
            correct = known and fr.correct
            by_field[fr.field].append((decidable, known, correct, fr.quote_verified))

    per_field: dict[str, ExtractFieldMetrics] = {}
    total_decidable = 0
    total_known_of_decidable = 0
    total_correct_of_known = 0
    total_known_count = 0
    total_quote_verified = 0
    total_field_results = 0

    for field_name, rows in by_field.items():
        decidable_rows = [r for r in rows if r[0]]
        n_decidable = len(decidable_rows)
        known_of_decidable = sum(1 for r in decidable_rows if r[1])
        correct_of_known_decidable = sum(1 for r in decidable_rows if r[1] and r[2])

        per_field[field_name] = ExtractFieldMetrics(
            field=field_name,
            n_decidable=n_decidable,
            coverage=(known_of_decidable / n_decidable if n_decidable else 1.0),
            accuracy_when_known=(
                correct_of_known_decidable / known_of_decidable if known_of_decidable else 1.0
            ),
        )

        total_decidable += n_decidable
        total_known_of_decidable += known_of_decidable
        total_correct_of_known += correct_of_known_decidable
        total_known_count += sum(1 for r in rows if r[1])
        total_quote_verified += sum(1 for r in rows if r[1] and r[3])
        total_field_results += len(rows)

    return ExtractMetrics(
        mode=result.mode,
        n_documents=n_documents,
        per_field=per_field,
        overall_coverage=(total_known_of_decidable / total_decidable if total_decidable else 1.0),
        overall_accuracy_when_known=(
            total_correct_of_known / total_known_of_decidable if total_known_of_decidable else 1.0
        ),
        quote_verified_rate=(
            total_quote_verified / total_known_count if total_known_count else 1.0
        ),
        total_input_tokens=sum(d.input_tokens for d in documents),
        total_output_tokens=sum(d.output_tokens for d in documents),
        total_cost_usd=sum(d.cost_usd for d in documents),
        cost_known=all(d.cost_known for d in documents) if documents else True,
        mean_latency_ms=(
            sum(d.latency_ms for d in documents) / n_documents if n_documents else 0.0
        ),
    )

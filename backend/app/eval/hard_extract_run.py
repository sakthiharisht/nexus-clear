"""Hard Extract eval (M6.1 #4): scores each app/eval/generator/
hard_extraction_set.py case against its own ground truth, reusing the
same field-comparison primitives app/eval/extract_run.py uses for the
main 12-packet corpus (values_match, str_or_none, flat_field_results,
CV_POSITION_FIELDS) - same scoring methodology, a deliberately harder
corpus.

n=30 across 6 categories (noisy_layout, narrative, multi_page,
unusual_cv, ambiguous_date, name_suffix) - see app/eval/report.py's
caveat: too small to rank tiers against each other or against the
main 12-packet set's numbers. Read per-category, not as one blended
score - a model's narrative-reading ability and its multi-page
handling are different capabilities that happen to average out
otherwise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from app.backends.extract_cache import ExtractionBackend, MissingFixtureError
from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    ExtractInput,
    LicenseExtraction,
)
from app.core.extract_verify import (
    VerifiedCvPosition,
    verify_coi_extraction,
    verify_cv_extraction,
    verify_license_extraction,
)
from app.eval.extract_run import (
    COI_FIELDS,
    CV_POSITION_FIELDS,
    LICENSE_FIELDS,
    flat_field_results,
    full_text,
    str_or_none,
    values_match,
)
from app.eval.extract_types import DocumentExtraction, ExtractModeResult, FieldResult

logger = logging.getLogger(__name__)


def load_hard_extraction_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = data["cases"]
    return cases


def build_hard_extract_input(case: dict[str, Any], fixtures_root: Path) -> ExtractInput:
    text = full_text(fixtures_root / case["path"]) or ""
    return ExtractInput(
        doc_id=case["case_id"],
        kind=case["kind"],
        filename=case["path"],
        document_text=text,
    )


def _cv_hard_field_results(
    expected_positions: list[dict[str, Any]], verified_positions: list[VerifiedCvPosition]
) -> list[FieldResult]:
    results = []
    for i in range(max(len(expected_positions), len(verified_positions))):
        gt = expected_positions[i] if i < len(expected_positions) else None
        pred = verified_positions[i] if i < len(verified_positions) else None
        for name in CV_POSITION_FIELDS:
            expected = None if gt is None else str_or_none(gt.get(name))
            if pred is None:
                predicted = None
                status: Literal["known", "unknown"] = "unknown"
                quote_verified = False
            else:
                field = pred[name]  # type: ignore[literal-required]
                predicted = field.value if field.status == "known" else None
                status = field.status
                quote_verified = field.quote_verified
            results.append(
                FieldResult(
                    field=f"cv.positions[{i}].{name}",
                    expected=expected,
                    predicted=predicted,
                    status=status,
                    quote_verified=quote_verified,
                    correct=values_match(expected, predicted),
                )
            )
    return results


def _field_results_for_case(
    case: dict[str, Any], fields: Any, document_text: str | None
) -> list[FieldResult]:
    kind = case["kind"]
    if kind == "license":
        assert isinstance(fields, LicenseExtraction)
        verified = verify_license_extraction(fields, document_text)
        return flat_field_results("license", LICENSE_FIELDS, case["expected_fields"], verified)
    if kind == "coi":
        assert isinstance(fields, CoiExtraction)
        verified = verify_coi_extraction(fields, document_text)
        return flat_field_results("coi", COI_FIELDS, case["expected_fields"], verified)
    assert isinstance(fields, CvExtraction)
    cv_verified = verify_cv_extraction(fields, document_text)
    return _cv_hard_field_results(case["expected_positions"], cv_verified["positions"])


def run_hard_extract(
    cases: list[dict[str, Any]],
    fixtures_root: Path,
    *,
    mode_name: str,
    backend: ExtractionBackend,
) -> ExtractModeResult:
    documents: list[DocumentExtraction] = []
    for case in cases:
        extract_input = build_hard_extract_input(case, fixtures_root)
        try:
            result = backend.extract(extract_input)
        except (ValueError, MissingFixtureError) as exc:
            logger.warning(
                "hard extract failed for case=%s backend=%s: %s",
                case["case_id"],
                backend.name,
                exc,
            )
            documents.append(
                DocumentExtraction(
                    packet_id=case["case_id"],
                    slot=case["category"],
                    kind=case["kind"],
                    decided_by=backend.name,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    cost_known=True,
                    latency_ms=0.0,
                    simulated=False,
                    field_results=[],
                )
            )
            continue

        field_results = _field_results_for_case(
            case, result.fields, extract_input.document_text or None
        )
        documents.append(
            DocumentExtraction(
                packet_id=case["case_id"],
                slot=case["category"],
                kind=case["kind"],
                decided_by=result.decided_by,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                cost_known=result.cost_known,
                latency_ms=result.latency_ms,
                simulated=result.simulated,
                field_results=field_results,
            )
        )

    final_mode = f"{mode_name}-SIMULATED" if any(d.simulated for d in documents) else mode_name
    return ExtractModeResult(mode=final_mode, documents=documents)

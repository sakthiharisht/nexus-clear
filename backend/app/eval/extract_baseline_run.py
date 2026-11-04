"""Wraps the M3 regex-only baseline (app/eval/baseline_extraction.py)
into the same ExtractModeResult/FieldResult shape Extract's Claude
tiers use (app/eval/extract_run.py), so app/eval/report.py can render
both in one comparison table (SPEC.md section 14, M6: "compared
against the M3 regex baseline").

quote_verified is always True for a baseline-extracted field: baseline
never guesses by construction (it only emits a value when its regex
matched a "Label: value" line in the document's real text layer), a
stronger per-field guarantee than Extract's citation check even though
it isn't the same mechanism (no model, no separate quote string).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from app.eval.baseline_extraction import extract_baseline_facts
from app.eval.extract_run import COI_FIELDS as _COI_FIELDS
from app.eval.extract_run import CV_POSITION_FIELDS, LICENSE_FIELDS, str_or_none, values_match
from app.eval.extract_types import DocumentExtraction, ExtractModeResult, FieldResult
from app.rules.context import CvFacts


def _flat_baseline_results(
    prefix: str, field_names: tuple[str, ...], ground_truth: dict[str, Any], facts_obj: Any
) -> list[FieldResult]:
    results = []
    for name in field_names:
        expected = str_or_none(ground_truth.get(name))
        predicted = str_or_none(getattr(facts_obj, name))
        status: Literal["known", "unknown"] = "known" if predicted is not None else "unknown"
        results.append(
            FieldResult(
                field=f"{prefix}.{name}",
                expected=expected,
                predicted=predicted,
                status=status,
                quote_verified=True,
                correct=values_match(expected, predicted),
            )
        )
    return results


def _cv_baseline_results(packet: dict[str, Any], cv_facts: CvFacts) -> list[FieldResult]:
    gt_positions: list[dict[str, Any]] = packet["facts"]["cv"]["positions"]
    pred_positions = cv_facts.positions
    results = []
    for i in range(max(len(gt_positions), len(pred_positions))):
        gt = gt_positions[i] if i < len(gt_positions) else None
        pred = pred_positions[i] if i < len(pred_positions) else None
        for name in CV_POSITION_FIELDS:
            expected = None if gt is None else str_or_none(gt.get(name))
            predicted = str_or_none(getattr(pred, name)) if pred is not None else None
            status: Literal["known", "unknown"] = "known" if predicted is not None else "unknown"
            results.append(
                FieldResult(
                    field=f"cv.positions[{i}].{name}",
                    expected=expected,
                    predicted=predicted,
                    status=status,
                    quote_verified=True,
                    correct=values_match(expected, predicted),
                )
            )
    return results


def run_extract_baseline(ground_truth: dict[str, Any], fixtures_root: Path) -> ExtractModeResult:
    documents: list[DocumentExtraction] = []
    for packet in ground_truth["packets"]:
        facts, _notes = extract_baseline_facts(packet, fixtures_root)
        doc_facts_by_slot = {d["slot"]: d for d in packet["facts"]["documents"]}

        license_doc_fact = doc_facts_by_slot.get("license")
        if license_doc_fact and license_doc_fact["uploaded_doc_type"] == "texas_lpc_license":
            documents.append(
                DocumentExtraction(
                    packet_id=packet["packet_id"],
                    slot="license",
                    kind="license",
                    decided_by="code",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    cost_known=True,
                    latency_ms=0.0,
                    simulated=False,
                    field_results=_flat_baseline_results(
                        "license", LICENSE_FIELDS, packet["facts"]["license"], facts.license
                    ),
                )
            )

        coi_doc_fact = doc_facts_by_slot.get("coi")
        if coi_doc_fact and coi_doc_fact["uploaded_doc_type"] == "malpractice_coi":
            documents.append(
                DocumentExtraction(
                    packet_id=packet["packet_id"],
                    slot="coi",
                    kind="coi",
                    decided_by="code",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    cost_known=True,
                    latency_ms=0.0,
                    simulated=False,
                    field_results=_flat_baseline_results(
                        "coi", _COI_FIELDS, packet["facts"]["coi"], facts.coi
                    ),
                )
            )

        cv_doc_fact = doc_facts_by_slot.get("cv")
        if cv_doc_fact and cv_doc_fact["uploaded_doc_type"] == "cv":
            documents.append(
                DocumentExtraction(
                    packet_id=packet["packet_id"],
                    slot="cv",
                    kind="cv",
                    decided_by="code",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    cost_known=True,
                    latency_ms=0.0,
                    simulated=False,
                    field_results=_cv_baseline_results(packet, facts.cv),
                )
            )

    return ExtractModeResult(mode="extract-baseline", documents=documents)

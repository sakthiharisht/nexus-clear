"""Runs Extract (SPEC.md section 7.3) against the 12 real packets for a
given ExtractionBackend - parallel to app/eval/classify_run.py, scored
against ground truth instead of just recorded.

Scope: only license/coi/cv are field-accuracy-scored here, against
app/eval/baseline_extraction.py's (M3) same ground truth source
(packet["facts"]). education/w9 extraction schemas exist and are
citation-verified (app/core/extract_verify.py, tested directly) but
have no ground-truth field values in this fixture set at all - M3's
own regex baseline never extracted them either (SPEC's
education/w9 required_slots are presence/legibility checks only, no
rule reads an extracted field) - so there is nothing honest to score
them against here. Scoring them anyway against nothing would just be
inventing a number.

A slot is only scored against its own schema when the real uploaded
document actually is that type (`uploaded_doc_type` ground truth, not
the slot's expected type) - the same gate app/eval/baseline_extraction.py
uses. D09 (wrong document in slot) correctly contributes nothing to
license-field scoring for that slot: there is no license to extract
from a CV.

Deliberately does NOT attach page images, for the same cross-platform
cache-key reproducibility reason as app/eval/classify_run.py's module
docstring (PNG rendering isn't byte-identical across Windows dev and
Linux CI) - document_text is this eval's only model input signal, same
as Classify's.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import pypdf

from app.backends.extract_cache import ExtractionBackend
from app.backends.extract_types import (
    DOC_TYPE_TO_EXTRACT_KIND,
    CoiExtraction,
    CvExtraction,
    ExtractInput,
    ExtractionResult,
    ExtractKind,
    LicenseExtraction,
)
from app.core.extract_verify import (
    VerifiedCv,
    VerifiedCvPosition,
    verify_coi_extraction,
    verify_cv_extraction,
    verify_license_extraction,
)
from app.eval.extract_types import DocumentExtraction, ExtractModeResult, FieldResult

logger = logging.getLogger(__name__)

LICENSE_FIELDS = (
    "holder_name",
    "license_number",
    "license_type",
    "status",
    "issue_date",
    "expiration_date",
    "issuing_board",
)
COI_FIELDS = (
    "insured_name",
    "carrier",
    "policy_number",
    "effective_date",
    "expiration_date",
    "per_occurrence",
    "aggregate",
)
CV_POSITION_FIELDS = ("title", "employer", "start", "end")

_SCORED_SLOTS: dict[str, ExtractKind] = {"license": "license", "coi": "coi", "cv": "cv"}


def _full_text(path: Path) -> str | None:
    """Whole-document text (single page, per app/backends/extract_types.py's
    ExtractInput docstring), or None for anything pypdf can't read (an
    image scan) - the caller treats None the same way as an empty text
    layer: nothing to verify a quote against."""
    if path.suffix.lower() != ".pdf":
        return None
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return None
    if not reader.pages:
        return None
    text = reader.pages[0].extract_text() or ""
    return text if text.strip() else None


def build_extract_input(
    packet: dict[str, Any], slot: str, kind: ExtractKind, fixtures_root: Path
) -> ExtractInput:
    rel_path = packet["documents"][slot]
    text = _full_text(fixtures_root / rel_path) or ""
    return ExtractInput(
        doc_id=f"doc-{slot}",
        kind=kind,
        filename=f"{packet['packet_id']}/{Path(rel_path).name}",
        document_text=text,
    )


def values_match(expected: str | None, predicted: str | None) -> bool:
    if expected is None and predicted is None:
        return True
    if expected is None or predicted is None:
        return False
    try:
        return float(expected) == float(predicted)
    except ValueError:
        return expected.strip().lower() == predicted.strip().lower()


def str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _flat_field_results(
    prefix: str,
    field_names: tuple[str, ...],
    ground_truth: dict[str, Any],
    verified: dict[str, Any],
) -> list[FieldResult]:
    results = []
    for name in field_names:
        expected = str_or_none(ground_truth.get(name))
        field = verified[name]
        predicted = field.value if field.status == "known" else None
        results.append(
            FieldResult(
                field=f"{prefix}.{name}",
                expected=expected,
                predicted=predicted,
                status=field.status,
                quote_verified=field.quote_verified,
                correct=values_match(expected, predicted),
            )
        )
    return results


def _cv_field_results(packet: dict[str, Any], verified: VerifiedCv) -> list[FieldResult]:
    gt_positions: list[dict[str, Any]] = packet["facts"]["cv"]["positions"]
    pred_positions: list[VerifiedCvPosition] = verified["positions"]
    results = []
    for i in range(max(len(gt_positions), len(pred_positions))):
        gt = gt_positions[i] if i < len(gt_positions) else None
        pred = pred_positions[i] if i < len(pred_positions) else None
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


def _field_results_for(
    kind: ExtractKind, packet: dict[str, Any], result: ExtractionResult, document_text: str | None
) -> list[FieldResult]:
    if kind == "license":
        assert isinstance(result.fields, LicenseExtraction)
        license_verified = verify_license_extraction(result.fields, document_text)
        return _flat_field_results(
            "license", LICENSE_FIELDS, packet["facts"]["license"], license_verified
        )
    if kind == "coi":
        assert isinstance(result.fields, CoiExtraction)
        coi_verified = verify_coi_extraction(result.fields, document_text)
        return _flat_field_results("coi", COI_FIELDS, packet["facts"]["coi"], coi_verified)
    assert isinstance(result.fields, CvExtraction)
    cv_verified = verify_cv_extraction(result.fields, document_text)
    return _cv_field_results(packet, cv_verified)


def run_extract(
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    *,
    mode_name: str,
    backend: ExtractionBackend,
) -> ExtractModeResult:
    documents: list[DocumentExtraction] = []
    for packet in ground_truth["packets"]:
        doc_facts_by_slot = {d["slot"]: d for d in packet["facts"]["documents"]}
        for slot, kind in _SCORED_SLOTS.items():
            if slot not in packet["documents"]:
                continue
            doc_fact = doc_facts_by_slot.get(slot)
            true_doc_type: str | None = doc_fact["uploaded_doc_type"] if doc_fact else None
            if true_doc_type is None or DOC_TYPE_TO_EXTRACT_KIND.get(true_doc_type) != kind:
                # The physical slot doesn't hold the document type this
                # schema expects (e.g. D09: a CV in the license slot) -
                # nothing for this schema to score, same as M3 baseline.
                continue

            extract_input = build_extract_input(packet, slot, kind, fixtures_root)
            try:
                result = backend.extract(extract_input)
            except ValueError as exc:
                # Same failure mode as app/eval/classify_run.py's
                # ValueError handling: the model never emitted a parsed
                # structured output. Treated as "nothing extracted" -
                # every field reports unknown - not a crash, and not a
                # guess either.
                logger.warning(
                    "extract failed for packet=%s slot=%s backend=%s: %s",
                    packet["packet_id"],
                    slot,
                    backend.name,
                    exc,
                )
                documents.append(
                    DocumentExtraction(
                        packet_id=packet["packet_id"],
                        slot=slot,
                        kind=kind,
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

            field_results = _field_results_for(
                kind, packet, result, extract_input.document_text or None
            )
            documents.append(
                DocumentExtraction(
                    packet_id=packet["packet_id"],
                    slot=slot,
                    kind=kind,
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

"""Runs Classify (SPEC.md section 7.2) against the 12 real packets for
a given DecisionBackend/policy configuration - parallel to
app/eval/run.py's ceiling/baseline modes, but evaluating per-document
classification instead of per-rule Finding status.

`build_classify_input` is shared with app/eval/classify_fixture_seed.py
so both build byte-for-byte the same ClassifyInput for a given
packet/slot - the record/replay cache (app/backends/cache.py) keys on
a hash of that input, so a mismatch here would mean every real eval
run misses a cache the seed script just finished writing.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pypdf

from app.backends.base import DecisionBackend
from app.backends.policy import decide
from app.backends.types import DOC_TYPES, ClassifyInput
from app.eval.classify_types import ClassifyModeResult, DocumentClassification

_IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _page1_text(path: Path) -> str:
    """Page-1 text only (SPEC 7.2's Classify input), unlike
    app/eval/baseline_extraction.py's `_read_text` which joins every
    page - Classify is a cheap first look, not full extraction. Empty
    string (never None) for anything pypdf can't open (e.g. the PNG
    scans D10 renders) - Classify's `legible` question is exactly what
    should end up low for those, not a crash.
    """
    if path.suffix.lower() in _IMAGE_MEDIA_TYPES:
        return ""
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return ""
    if not reader.pages:
        return ""
    return reader.pages[0].extract_text() or ""


def _page1_image(path: Path) -> tuple[str, str] | None:
    """The raw image bytes, base64-encoded, when `path` already is one
    (SPEC 7.2's page-1 image input) - rendering a *textless PDF* page
    to an image would need a PDF rasterizer this project doesn't carry
    (no document in the 12 packets needs it: the only no-text-layer
    documents are literal PNGs, confirmed via the generator's defect
    mutations), so that case isn't handled here.
    """
    media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        return None
    return base64.b64encode(path.read_bytes()).decode(), media_type


def build_classify_input(packet: dict[str, Any], slot: str, fixtures_root: Path) -> ClassifyInput:
    rel_path = packet["documents"][slot]
    path = fixtures_root / rel_path
    text = _page1_text(path)

    image_b64: str | None = None
    media_type: str | None = None
    if not text.strip():
        image = _page1_image(path)
        if image is not None:
            image_b64, media_type = image

    return ClassifyInput(
        slot=slot,
        filename=Path(rel_path).name,
        allowed_doc_types=list(DOC_TYPES),
        page1_text=text,
        page1_image_b64=image_b64,
        page1_image_media_type=media_type,  # type: ignore[arg-type]
    )


def run_classify(
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    *,
    mode_name: str,
    primary: DecisionBackend,
    fallback: DecisionBackend | None,
    tau_classify: float,
    legible_threshold: float,
) -> ClassifyModeResult:
    documents: list[DocumentClassification] = []
    for packet in ground_truth["packets"]:
        for doc_fact in packet["facts"]["documents"]:
            slot = doc_fact["slot"]
            if slot not in packet["documents"]:
                continue  # nothing uploaded to this slot - nothing to classify

            classify_input = build_classify_input(packet, slot, fixtures_root)
            classify_decision = decide(
                classify_input,
                primary=primary,
                fallback=fallback,
                tau_classify=tau_classify,
                legible_threshold=legible_threshold,
            )
            result = classify_decision.result
            top_probability = max(result.probabilities.values()) if result.probabilities else 0.0
            documents.append(
                DocumentClassification(
                    packet_id=packet["packet_id"],
                    slot=slot,
                    expected_doc_type=doc_fact["expected_doc_type"],
                    true_doc_type=doc_fact["uploaded_doc_type"],
                    predicted_doc_type=result.doc_type,
                    predicted_probability=top_probability,
                    predicted_legible=result.legible,
                    predicted_slot_match=result.slot_match,
                    accepted=classify_decision.accepted,
                    escalated=classify_decision.escalated,
                    decided_by=result.decided_by,
                    cost_usd=result.cost_usd,
                    latency_ms=result.latency_ms,
                )
            )
    return ClassifyModeResult(mode=mode_name, documents=documents)

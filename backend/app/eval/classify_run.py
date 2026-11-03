"""Runs Classify (SPEC.md section 7.2) against the 12 real packets for
a given DecisionBackend/policy configuration - parallel to
app/eval/run.py's ceiling/baseline modes, but evaluating per-document
classification instead of per-rule Finding status.

`build_classify_input` is shared with app/eval/classify_fixture_seed.py
so both build byte-for-byte the same ClassifyInput for a given
packet/slot - the record/replay cache (app/backends/cache.py) keys on
a hash of that input, so a mismatch here would mean every real eval
run misses a cache the seed script just finished writing.

Deliberately does NOT attach page-1 image bytes here, even though
SPEC 7.2 and both backends support it (app/backends/claude_backend.py,
jev_backend.py each have dedicated, passing tests for it against
synthetic bytes). Image rendering (the two D10/benign-2 PNG scans) is
not byte-identical across platforms - a fixture cache seeded on one OS
misses on another, which is exactly what broke CI here: this eval runs
on Linux CI but was seeded from a Windows dev machine. Text extraction
(pypdf over reportlab-generated PDFs) IS cross-platform stable, so
page1_text is the only signal this eval's cache keys depend on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pypdf

from app.backends.base import DecisionBackend
from app.backends.policy import decide
from app.backends.types import DOC_TYPES, ClassifyInput
from app.eval.classify_types import ClassifyModeResult, DocumentClassification

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def _page1_text(path: Path) -> str:
    """Page-1 text only (SPEC 7.2's Classify input), unlike
    app/eval/baseline_extraction.py's `_read_text` which joins every
    page - Classify is a cheap first look, not full extraction. Empty
    string (never None) for anything pypdf can't open (e.g. the PNG
    scans D10 renders) - Classify's `legible` question is exactly what
    should end up low for those, not a crash.
    """
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        return ""
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return ""
    if not reader.pages:
        return ""
    return reader.pages[0].extract_text() or ""


def build_classify_input(packet: dict[str, Any], slot: str, fixtures_root: Path) -> ClassifyInput:
    rel_path = packet["documents"][slot]
    text = _page1_text(fixtures_root / rel_path)
    return ClassifyInput(
        slot=slot,
        # Prefixed with packet_id, not just the bare basename: every
        # packet names its license slot file "license.png"/"license.pdf"
        # etc, so two different packets' same-slot documents would
        # otherwise collide on an identical (slot, filename, text) input
        # whenever text is empty - exactly what happened between
        # benign-2-rotated-scan and defective-7's license scans before
        # this fix.
        filename=f"{packet['packet_id']}/{Path(rel_path).name}",
        allowed_doc_types=list(DOC_TYPES),
        page1_text=text,
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
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                    latency_ms=result.latency_ms,
                    simulated=result.simulated,
                )
            )

    # M5.1 "eval honesty": a mode with even one simulated document gets
    # marked in the label itself, not just in a field a report could
    # silently drop - see ClassifyModeResult's docstring.
    final_mode = f"{mode_name}-SIMULATED" if any(d.simulated for d in documents) else mode_name
    return ClassifyModeResult(mode=final_mode, documents=documents)

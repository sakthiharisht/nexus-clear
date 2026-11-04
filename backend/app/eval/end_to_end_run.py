"""End-to-end eval (M7 #6, SPEC.md section 14): rules findings on the
12 real packets built the way a real case actually would be - Extract
(app/backends/claude_extractor.py) feeding Reconcile
(app/reconcile/engine.py) feeding Validate (app/rules/engine.py) -
scored with the exact same app/eval/metrics.py machinery the M3
ceiling/baseline modes already use, so this mode's row lands in the
same comparison table (exact match, primary defect detected, false
positives on clean/benign, coverage, accuracy_when_decided) rather
than needing a parallel report format.

Scope matches app/eval/extract_run.py's own: only license/coi/cv
project into CaseFacts (nothing else has anywhere to go - see that
module's and app/pipeline/extract_to_case_facts.py's docstrings), and
a slot is only fed to Extract when the real uploaded document type
matches what that slot's schema expects (D09's wrong-document-in-slot
correctly contributes nothing there, same as the text-only extract
eval and the M3 baseline).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from app.backends.extract_cache import ExtractionBackend
from app.backends.extract_types import (
    DOC_TYPE_TO_EXTRACT_KIND,
    CoiExtraction,
    CvExtraction,
    ExtractKind,
    LicenseExtraction,
)
from app.eval.extract_run import build_extract_input
from app.eval.types import ModeResult, PacketResult
from app.pipeline.extract_to_case_facts import (
    apply_coi_extraction,
    apply_cv_extraction,
    apply_license_extraction,
)
from app.reconcile.engine import reconcile
from app.reconcile.investigator import InvestigatorLike
from app.rules.context import CaseFacts, DocumentFact, ProfileFacts, SupervisionFacts
from app.rules.engine import evaluate_rule_pack
from app.rules.schema import RulePack

_SCORED_SLOTS: dict[str, ExtractKind] = {"license": "license", "coi": "coi", "cv": "cv"}


def _extract_case_facts(
    packet: dict[str, Any], fixtures_root: Path, extractor: ExtractionBackend
) -> tuple[CaseFacts, list[str]]:
    notes: list[str] = []
    documents = [DocumentFact(**d) for d in packet["facts"]["documents"]]
    gt_facts = packet["facts"]
    facts = CaseFacts(
        target_date=date.fromisoformat(packet["target_date"]),
        profile=ProfileFacts(**gt_facts["profile"]),
        supervision=SupervisionFacts(**gt_facts["supervision"]),
        documents=documents,
    )

    doc_facts_by_slot = {d["slot"]: d for d in packet["facts"]["documents"]}
    for slot, kind in _SCORED_SLOTS.items():
        if slot not in packet["documents"]:
            continue
        doc_fact = doc_facts_by_slot.get(slot)
        true_doc_type = doc_fact["uploaded_doc_type"] if doc_fact else None
        if true_doc_type is None or DOC_TYPE_TO_EXTRACT_KIND.get(true_doc_type) != kind:
            notes.append(f"{slot}: uploaded doc type doesn't match this schema - not extracted")
            continue

        extract_input = build_extract_input(packet, slot, kind, fixtures_root)
        if not extract_input.document_text:
            # A scanned/image document with no text layer - this eval
            # path doesn't attach page images (same reason as extract_run.py's
            # own docstring), so there is no model input signal at all.
            # Note it the same way baseline_extraction.py does, and skip the
            # call rather than spend one on an input with nothing to read.
            notes.append(f"{slot}: no extractable text layer - left unknown")
            continue
        try:
            result = extractor.extract(extract_input)
        except ValueError as exc:
            notes.append(f"{slot}: extraction failed ({exc}) - left unknown")
            continue

        document_text = extract_input.document_text or None
        doc_id = f"doc-{slot}"
        if kind == "license":
            assert isinstance(result.fields, LicenseExtraction)
            facts = apply_license_extraction(facts, doc_id, result.fields, document_text)
        elif kind == "coi":
            assert isinstance(result.fields, CoiExtraction)
            facts = apply_coi_extraction(facts, doc_id, result.fields, document_text)
        else:
            assert isinstance(result.fields, CvExtraction)
            facts = apply_cv_extraction(facts, doc_id, result.fields, document_text)

    return facts, notes


def run_end_to_end(
    pack: RulePack,
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    *,
    mode_name: str,
    extractor: ExtractionBackend,
    investigator: InvestigatorLike,
) -> ModeResult:
    packets: list[PacketResult] = []
    for packet in ground_truth["packets"]:
        facts, notes = _extract_case_facts(packet, fixtures_root, extractor)
        facts = reconcile(pack, facts, investigator=investigator)
        findings = evaluate_rule_pack(pack, facts, facts.target_date)
        packets.append(
            PacketResult(
                packet_id=packet["packet_id"],
                kind=packet["kind"],
                defect_ids=packet["defect_ids"],
                actual={f.finding_id: f.status for f in findings},
                expected=packet["expected_findings"],
                extraction_notes=notes,
            )
        )
    return ModeResult(mode=mode_name, packets=packets)

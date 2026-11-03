"""Non-LLM baseline extraction (SPEC.md section 14, M3): read the rendered
packet documents and build CaseFacts using only a PDF text layer + regex/
keyword heuristics — no OCR, no vision model, no LLM. A document without a
readable text layer (a PNG scan, or a PDF pypdf can't parse) yields
`unknown` for every field it would have supplied — never a guess
(CLAUDE.md invariant 2).

profile.* (legal_name, practice_name, npi) and supervision.supervisor_count
are NOT extracted from any document here: per SPEC.md section 5, they are
`provider_profile` — intake-form data the provider types in directly, not
something OCR'd off a credential. Taken straight from the ground truth's
facts (the real pipeline would take it from the case's intake form, which
this project doesn't render as a document at all).

Field extraction is regex matching against this project's own renderer
(app/eval/generator/documents.py)'s exact "Label: value" line format — a
deliberately simple baseline, not a general-purpose document parser. Its
job is to be a honest, reliable floor for whatever a document's text
layer actually says, not to be clever.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import pypdf

from app.eval.generator.mutations import SLOT_DOC_TYPES, SLOTS
from app.rules.context import (
    CaseFacts,
    CoiFacts,
    CvFacts,
    CvPosition,
    DocumentFact,
    LicenseFacts,
    ProfileFacts,
    SupervisionFacts,
)

_TITLE_TO_DOC_TYPE = {
    "Texas Licensed Professional Counselor": "texas_lpc_license",
    "Certificate of Malpractice Insurance": "malpractice_coi",
    "Curriculum Vitae": "cv",
    "Degree / Transcript": "degree_transcript",
    "Form W-9 (synthetic)": "w9",
}

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore all (previous|prior) instructions",
        r"system instruction",
        r"disregard (all |the )?(previous|prior) instructions",
    ]
]

_DATE_RE = r"\d{4}-\d{2}-\d{2}"
_POSITION_RE = re.compile(
    rf"^  (.+?), (.+?) \(({_DATE_RE}) - (present|{_DATE_RE})\)$", re.MULTILINE
)


def _read_text(path: Path) -> str | None:
    """Extracted text, or None if the file has no readable text layer."""
    if path.suffix.lower() != ".pdf":
        return None
    try:
        reader = pypdf.PdfReader(str(path))
        text = "\n".join(page.extract_text() for page in reader.pages)
    except Exception:
        return None
    return text if text.strip() else None


def _classify(text: str) -> str | None:
    lines = text.splitlines()
    first_line = lines[0].strip() if lines else ""
    return _TITLE_TO_DOC_TYPE.get(first_line)


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)}: (.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _money(text: str, label: str) -> float | None:
    value = _field(text, label)
    if value is None:
        return None
    try:
        return float(value.lstrip("$").replace(",", ""))
    except ValueError:
        return None


def _positions(text: str) -> list[CvPosition]:
    return [
        CvPosition(
            title=title,
            employer=employer,
            start=date.fromisoformat(start),
            end=None if end == "present" else date.fromisoformat(end),
        )
        for title, employer, start, end in _POSITION_RE.findall(text)
    ]


def _contains_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def extract_baseline_facts(
    packet: dict[str, Any], fixtures_root: Path
) -> tuple[CaseFacts, list[str]]:
    notes: list[str] = []
    documents: list[DocumentFact] = []
    license_fields: dict[str, Any] = {}
    coi_fields: dict[str, Any] = {}
    cv_positions: list[CvPosition] = []

    for slot in SLOTS:
        doc_id = f"doc-{slot}"
        expected_doc_type = SLOT_DOC_TYPES[slot]
        rel_path = packet["documents"].get(slot)

        if rel_path is None:
            notes.append(f"{slot}: no document uploaded")
            documents.append(
                DocumentFact(
                    doc_id=doc_id, slot=slot, expected_doc_type=expected_doc_type, readable=False
                )
            )
            continue

        text = _read_text(fixtures_root / rel_path)
        if text is None:
            notes.append(f"{slot}: no extractable text layer ({rel_path}) — unknown")
            documents.append(
                DocumentFact(
                    doc_id=doc_id, slot=slot, expected_doc_type=expected_doc_type, readable=False
                )
            )
            continue

        uploaded_doc_type = _classify(text)
        if uploaded_doc_type is None:
            notes.append(f"{slot}: text extracted but title didn't match a known doc type")

        documents.append(
            DocumentFact(
                doc_id=doc_id,
                slot=slot,
                expected_doc_type=expected_doc_type,
                uploaded_doc_type=uploaded_doc_type,
                legible_score=0.95 if uploaded_doc_type is not None else None,
                contains_injection_text=_contains_injection(text),
                readable=True,
            )
        )

        if slot == "license" and uploaded_doc_type == "texas_lpc_license":
            license_fields = {
                "holder_name": _field(text, "Holder name"),
                "license_number": _field(text, "License number"),
                "license_type": _field(text, "License type"),
                "status": _field(text, "Status"),
                "issue_date": _parse_date(_field(text, "Issue date")),
                "expiration_date": _parse_date(_field(text, "Expiration date")),
                "issuing_board": _field(text, "Issuing board"),
            }
        elif slot == "coi" and uploaded_doc_type == "malpractice_coi":
            coi_fields = {
                "insured_name": _field(text, "Insured"),
                "carrier": _field(text, "Carrier"),
                "policy_number": _field(text, "Policy number"),
                "effective_date": _parse_date(_field(text, "Effective date")),
                "expiration_date": _parse_date(_field(text, "Expiration date")),
                "per_occurrence": _money(text, "Per occurrence"),
                "aggregate": _money(text, "Aggregate"),
            }
        elif slot == "cv" and uploaded_doc_type == "cv":
            cv_positions = _positions(text)

    gt_facts = packet["facts"]
    facts = CaseFacts(
        target_date=date.fromisoformat(packet["target_date"]),
        license=LicenseFacts(doc_id="doc-license", **license_fields),
        coi=CoiFacts(doc_id="doc-coi", **coi_fields),
        cv=CvFacts(doc_id="doc-cv", positions=cv_positions),
        profile=ProfileFacts(**gt_facts["profile"]),
        supervision=SupervisionFacts(**gt_facts["supervision"]),
        documents=documents,
        # No Reconcile stage or MCP tools exist pre-LLM — these always stay
        # unresolved at baseline (see CaseFacts's own docstring).
        name_match_probabilities={},
        registry_results={},
    )
    return facts, notes

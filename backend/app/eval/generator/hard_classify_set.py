"""Hard classify set (M5.1 housekeeping #2): ~30 adversarial synthetic
documents that stress-test Classify (SPEC.md 7.2) specifically, not
the rules engine - a different purpose from the 12-packet corpus
(app/eval/generator/packets.py), which targets the defect catalog
(D01-D15), not classifier robustness. Reuses that module's rendering
primitives (write_pdf/write_scan_image/DocumentContent) directly rather
than the packet/defect machinery, which is overkill for a flat list of
one-document "cases."

Five categories:
- lookalike: structurally similar to a real COI/W-9 but genuinely a
  different kind of document (general liability vs malpractice
  insurance, a 1099/W-4 vs a W-9) - true_doc_type is "other".
- cv_license_text: a real CV whose content happens to mention license
  numbers/boards prominently - true_doc_type stays "cv"; the test is
  whether that derails doc_type, not whether the file really is one.
- degraded_scan: a real document rendered as a heavily blurred/noisy/
  low-contrast scan (or with content truncated, simulating a partial
  scan) - true_doc_type is unchanged; the test is legibility/accuracy
  under degradation.
- mixed_content: one page carrying two documents' content, the second
  visually set apart as a distinct block - true_doc_type is whichever
  content dominates the page (the other is noise a real extractor
  would have to see past).
- wrong_slot: real, undegraded content for one type, uploaded into a
  slot that expects a different type (expected_doc_type, from the
  slot, differs from true_doc_type, what the content actually is).

The manifest (hard_classify_ground_truth.json) deliberately mirrors
app/eval/generator/build.py's "packets" shape (packet_id/documents/
facts.documents) so app/eval/classify_run.py's existing
build_classify_input/run_classify work against it completely
unchanged - this is not its own packet format, just a one-document-
per-"packet" instance of the same one.

Deterministic: one seeded Faker/provider (SEED below, distinct from
the 12-packet corpus's own DEFAULT_SEED so the two don't entangle),
reportlab's invariant=1 canvas, Pillow's degradation filters already
verified deterministic for the main corpus (app/eval/generator/
documents.py).
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from faker import Faker

from app.eval.generator.documents import (
    DocumentContent,
    coi_content,
    cv_content,
    education_content,
    license_content,
    w9_content,
    write_pdf,
    write_scan_image,
)
from app.eval.generator.provider import ProviderSpec, build_provider

SEED = 2026110401
TARGET_DATE = date(2026, 11, 17)


@dataclass(frozen=True)
class HardCase:
    case_id: str
    category: str
    slot: str
    expected_doc_type: str
    true_doc_type: str
    description: str
    content: DocumentContent
    legible_score: float = 0.95
    degrade: bool = False
    truncate_lines: int | None = None


def _lookalikes(p: ProviderSpec) -> list[HardCase]:
    return [
        HardCase(
            "hard-lookalike-general-liability",
            "lookalike",
            "coi",
            "malpractice_coi",
            "other",
            "general liability cert, not malpractice - structurally COI-shaped",
            DocumentContent(
                "Certificate of General Liability Insurance",
                [
                    f"Insured: {p.coi_insured_name}",
                    f"Carrier: {p.coi_carrier}",
                    f"Policy number: GL-{p.coi_policy_number}",
                    f"Effective date: {p.coi_effective_date.isoformat()}",
                    f"Expiration date: {p.coi_expiration_date.isoformat()}",
                    f"Each occurrence: ${p.coi_per_occurrence:,.0f}",
                    f"General aggregate: ${p.coi_aggregate:,.0f}",
                    "Coverage: general liability (not professional/malpractice)",
                ],
            ),
        ),
        HardCase(
            "hard-lookalike-workers-comp",
            "lookalike",
            "coi",
            "malpractice_coi",
            "other",
            "workers' comp cert, not malpractice - structurally COI-shaped",
            DocumentContent(
                "Certificate of Workers Compensation Insurance",
                [
                    f"Insured: {p.coi_insured_name}",
                    f"Carrier: {p.coi_carrier}",
                    f"Policy number: WC-{p.coi_policy_number}",
                    f"Effective date: {p.coi_effective_date.isoformat()}",
                    f"Expiration date: {p.coi_expiration_date.isoformat()}",
                    "Coverage: statutory workers' compensation",
                ],
            ),
        ),
        HardCase(
            "hard-lookalike-coi-binder",
            "lookalike",
            "coi",
            "malpractice_coi",
            "other",
            "an insurance binder (a promise of future coverage), not a certificate",
            DocumentContent(
                "Certificate of Insurance Binder",
                [
                    f"Insured: {p.coi_insured_name}",
                    f"Carrier: {p.coi_carrier}",
                    "This binder confirms coverage is being arranged; it is not",
                    "itself a certificate of currently effective insurance.",
                    f"Requested effective date: {p.coi_effective_date.isoformat()}",
                ],
            ),
        ),
        HardCase(
            "hard-lookalike-1099",
            "lookalike",
            "w9",
            "w9",
            "other",
            "a 1099-NEC, not a W-9 - structurally W9-shaped (name/TIN/signed)",
            DocumentContent(
                "IRS Form 1099-NEC (synthetic)",
                [
                    f"Payee name: {p.legal_name}",
                    f"Payer business name: {p.w9_business_name}",
                    f"Payee TIN: {p.w9_tin}  (synthetic, clearly-invalid format)",
                    "Nonemployee compensation: $45,000.00",
                ],
            ),
        ),
        HardCase(
            "hard-lookalike-w4",
            "lookalike",
            "w9",
            "w9",
            "other",
            "a W-4, not a W-9 - both are short IRS forms with a name/TIN field",
            DocumentContent(
                "IRS Form W-4 Employee Withholding Certificate (synthetic)",
                [
                    f"Employee name: {p.legal_name}",
                    f"SSN: 000-{p.index:02d}-{1000 + p.index:04d}  (synthetic)",
                    "Filing status: Single",
                    "Signed: yes",
                ],
            ),
        ),
        HardCase(
            "hard-lookalike-ss4",
            "lookalike",
            "w9",
            "w9",
            "other",
            "an SS-4 (EIN application), not a W-9",
            DocumentContent(
                "IRS Form SS-4 Application for EIN (synthetic)",
                [
                    f"Legal name: {p.legal_name}",
                    f"Trade name: {p.w9_business_name}",
                    "Reason for applying: Started new business",
                ],
            ),
        ),
    ]


def _cv_with_license_text(p: ProviderSpec) -> list[HardCase]:
    return [
        HardCase(
            "hard-cv-license-mention-1",
            "cv_license_text",
            "cv",
            "cv",
            "cv",
            "CV work history prominently mentions license number/board",
            DocumentContent(
                "Curriculum Vitae",
                [
                    f"Name: {p.legal_name}",
                    "",
                    "Licenses & Certifications:",
                    f"  Texas Licensed Professional Counselor, License {p.license_number}",
                    f"  Issuing board: {p.issuing_board}",
                    "",
                    "Work history:",
                    f"  Licensed Professional Counselor, {p.coi_carrier} Clinic "
                    f"({p.license_issue_date.isoformat()} - present)",
                ],
            ),
        ),
        HardCase(
            "hard-cv-license-mention-2",
            "cv_license_text",
            "cv",
            "cv",
            "cv",
            "CV first line echoes license-document phrasing",
            DocumentContent(
                "Texas Licensed Professional Counselor - Curriculum Vitae",
                [
                    f"Name: {p.legal_name}",
                    f"License number: {p.license_number}",
                    "",
                    "Work history:",
                    f"  Licensed Professional Counselor, {p.w9_business_name} "
                    f"({p.license_issue_date.isoformat()} - present)",
                ],
            ),
        ),
        HardCase(
            "hard-cv-license-mention-3",
            "cv_license_text",
            "cv",
            "cv",
            "cv",
            "CV with a dense licensing/compliance section",
            DocumentContent(
                "Curriculum Vitae",
                [
                    f"Name: {p.legal_name}",
                    "",
                    "Professional licensure:",
                    f"  Texas LPC, license {p.license_number}, status {p.license_status}",
                    f"  Issued {p.license_issue_date.isoformat()}, "
                    f"expires {p.license_expiration_date.isoformat()}",
                    f"  Issuing board: {p.issuing_board}",
                    "",
                    "Education:",
                    f"  {p.education_degree}, {p.education_institution}",
                ],
            ),
        ),
    ]


def _degraded_scans(p: ProviderSpec) -> list[HardCase]:
    bases: list[tuple[str, str, str, DocumentContent]] = [
        ("license", "texas_lpc_license", "license", license_content(p)),
        ("coi", "malpractice_coi", "coi", coi_content(p)),
        ("cv", "cv", "cv", cv_content(p)),
        ("education", "degree_transcript", "education", education_content(p)),
        ("w9", "w9", "w9", w9_content(p)),
    ]
    cases = [
        HardCase(
            f"hard-degraded-{slot}",
            "degraded_scan",
            slot,
            doc_type,
            doc_type,
            f"{label} rendered as a heavily degraded scan (low contrast, blur, noise)",
            content,
            legible_score=0.15,
            degrade=True,
        )
        for slot, doc_type, label, content in bases
    ]
    partials: list[tuple[str, str, str, DocumentContent]] = [
        ("license", "texas_lpc_license", "license", license_content(p)),
        ("coi", "malpractice_coi", "coi", coi_content(p)),
        ("w9", "w9", "w9", w9_content(p)),
    ]
    cases += [
        HardCase(
            f"hard-partial-{slot}",
            "degraded_scan",
            slot,
            doc_type,
            doc_type,
            f"{label} with content truncated, simulating a partial/cut-off scan",
            content,
            legible_score=0.30,
            degrade=True,
            truncate_lines=2,
        )
        for slot, doc_type, label, content in partials
    ]
    return cases


def _mixed_content(p: ProviderSpec) -> list[HardCase]:
    def _merged(dominant: DocumentContent, minority: DocumentContent) -> DocumentContent:
        return DocumentContent(
            dominant.title,
            [
                *dominant.lines,
                "",
                "--- (additional page content below) ---",
                minority.title,
                *minority.lines,
            ],
        )

    combos: list[tuple[str, str, str, DocumentContent, DocumentContent]] = [
        ("cv", "cv", "cv", cv_content(p), w9_content(p)),
        ("license", "texas_lpc_license", "license", license_content(p), coi_content(p)),
        ("education", "degree_transcript", "education", education_content(p), cv_content(p)),
        ("w9", "w9", "w9", w9_content(p), coi_content(p)),
        ("cv", "cv", "cv_2", cv_content(p), education_content(p)),
        ("license", "texas_lpc_license", "license_2", license_content(p), w9_content(p)),
    ]
    return [
        HardCase(
            f"hard-mixed-{tag}",
            "mixed_content",
            slot,
            doc_type,
            doc_type,
            f"{slot} content with a second document's content appended on the same page",
            _merged(dominant, minority),
        )
        for slot, doc_type, tag, dominant, minority in combos
    ]


def _wrong_slot(p: ProviderSpec) -> list[HardCase]:
    combos: list[tuple[str, str, str, DocumentContent]] = [
        ("license", "malpractice_coi", "coi", coi_content(p)),
        ("cv", "w9", "w9", w9_content(p)),
        ("w9", "degree_transcript", "education", education_content(p)),
        ("education", "cv", "cv", cv_content(p)),
        ("coi", "texas_lpc_license", "license", license_content(p)),
        ("w9", "malpractice_coi", "coi", coi_content(p)),
    ]
    return [
        HardCase(
            f"hard-wrong-slot-{true_type}-in-{slot}",
            "wrong_slot",
            slot,
            {"license": "texas_lpc_license", "coi": "malpractice_coi", "cv": "cv",
             "education": "degree_transcript", "w9": "w9"}[slot],
            true_type,
            f"real {true_type} content uploaded into the {slot} slot",
            content,
        )
        for slot, true_type, _, content in combos
    ]


def build_hard_cases(seed: int = SEED) -> list[HardCase]:
    Faker.seed(seed)
    fake = Faker()
    p = build_provider(0, TARGET_DATE, fake)
    return (
        _lookalikes(p)
        + _cv_with_license_text(p)
        + _degraded_scans(p)
        + _mixed_content(p)
        + _wrong_slot(p)
    )


def _render(case: HardCase, output_root: Path) -> Path:
    content = case.content
    if case.truncate_lines is not None:
        content = DocumentContent(content.title, content.lines[: case.truncate_lines])

    if case.degrade:
        path = output_root / "hard" / f"{case.case_id}.png"
        write_scan_image(
            path,
            content,
            blur_radius=2.5,
            noise_amount=4000,
            contrast_factor=0.35,
            add_shadow=True,
            # zlib.crc32, not Python's built-in hash(): str hashing is
            # randomized per-process (PYTHONHASHSEED) unless disabled,
            # which would make the degraded scans non-deterministic
            # across runs - confirmed by hitting exactly that bug
            # before adding this comment.
            seed=zlib.crc32(case.case_id.encode()),
        )
    else:
        path = output_root / "hard" / f"{case.case_id}.pdf"
        write_pdf(path, content)
    return path


def generate_hard_set(seed: int, output_root: Path) -> dict[str, Any]:
    cases = build_hard_cases(seed)
    packets_payload: list[dict[str, Any]] = []
    for case in cases:
        path = _render(case, output_root)
        packets_payload.append(
            {
                "packet_id": case.case_id,
                "category": case.category,
                "description": case.description,
                "documents": {case.slot: path.relative_to(output_root).as_posix()},
                "facts": {
                    "documents": [
                        {
                            "slot": case.slot,
                            "expected_doc_type": case.expected_doc_type,
                            "uploaded_doc_type": case.true_doc_type,
                            "legible_score": case.legible_score,
                        }
                    ]
                },
            }
        )

    manifest: dict[str, Any] = {"seed": seed, "packets": packets_payload}
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (output_root / "hard_classify_ground_truth.json").write_text(
        manifest_text, encoding="utf-8"
    )
    return manifest


def main() -> None:  # pragma: no cover - thin CLI wrapper, exercised via generate_hard_set in tests
    repo_root = Path(__file__).resolve().parents[4]
    output_root = repo_root / "eval" / "fixtures"
    generate_hard_set(SEED, output_root)
    print(f"Wrote hard classify set to {output_root}")


if __name__ == "__main__":  # pragma: no cover
    main()

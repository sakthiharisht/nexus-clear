"""Hard Extract set (M6.1 #4): ~25 synthetic documents that deliberately
break the one assumption the 12-packet corpus's documents all share -
a clean "Label: value" line per field, one page, unambiguous dates.
Each case carries its own ground-truth field values (unlike
app/eval/generator/hard_classify_set.py, which only needs a doc_type
label) so this set can be field-accuracy-scored the same way the main
12-packet corpus is (app/eval/extract_run.py), not just pass/fail.

Six categories, deliberately chosen to stress a different part of the
Extract pipeline:
  noisy_layout    - the label text itself varies (case, punctuation,
                     abbreviation, label-then-newline-then-value)
                     instead of the renderer's own fixed "Label: value"
                     convention - tests whether extraction depends on
                     that exact format or genuinely reads content.
  narrative       - no labels at all; fields are embedded in prose.
                     Directly exercises whether extraction is doing
                     real reading comprehension vs. pattern-matching
                     label text (the gap the M3 regex baseline cannot
                     cross by construction - it would score 0% here).
  multi_page      - fields split across two pages. Exercises the fix
                     in this change to app/eval/extract_run.py's
                     `full_text` (previously page 1 only, now joins
                     every page - every document in the main corpus
                     happens to be one page, so this was previously
                     untested).
  unusual_cv      - CV formatting the main corpus's cv_content never
                     produces: bulleted lines, reversed
                     employer/title order, abbreviated month names,
                     en-dash date ranges.
  ambiguous_date  - bare MM/DD/YYYY dates where day and month are both
                     <=12 (genuinely ambiguous without a locale
                     convention) alongside unambiguous controls (day
                     >12) - ground truth is always the US MM/DD/YYYY
                     reading, consistent with this project's Texas/US
                     context (app/core/normalize.py's own format list
                     only has %m/%d/%Y, not %d/%m/%Y, so DD/MM content
                     would misparse - this category makes that
                     assumption visible rather than silent).
  name_suffix     - names carrying a credential/generational suffix
                     ("Jane Doe, LPC-S", "John Smith Jr."). Ground
                     truth is the full printed string, not a
                     "canonicalized" bare name - canonicalizing would
                     itself be a guess beyond what the quote supports.

Rendered with the same deterministic reportlab canvas settings as
app/eval/generator/documents.py (`invariant=1`) - no Faker, no
randomness, so regenerating this set twice produces byte-identical
PDFs.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.backends.extract_types import ExtractKind

_WRAP_WIDTH = 85


@dataclass(frozen=True)
class HardExtractionCase:
    case_id: str
    category: str
    kind: ExtractKind
    description: str
    # One tuple of lines per page - each page rendered with its own
    # showPage(). A line longer than _WRAP_WIDTH is word-wrapped at
    # render time, not here, so narrative cases can be written as
    # plain long strings.
    pages: tuple[tuple[str, ...], ...]
    expected_fields: dict[str, str | None] = field(default_factory=dict)
    # Only for kind == "cv" - one dict per position, same field names
    # as app/eval/extract_run.py's CV_POSITION_FIELDS.
    expected_positions: tuple[dict[str, str | None], ...] = ()


def _render(path: Path, case: HardExtractionCase) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER, invariant=1)
    for page_lines in case.pages:
        c.setFont("Helvetica", 11)
        y = 740
        for raw_line in page_lines:
            wrapped = textwrap.wrap(raw_line, width=_WRAP_WIDTH) or [""]
            for line in wrapped:
                c.drawString(72, y, line)
                y -= 18
        c.showPage()
    c.save()


def _license(
    case_id: str,
    category: str,
    description: str,
    pages: tuple[tuple[str, ...], ...],
    *,
    holder_name: str | None = None,
    license_number: str | None = None,
    license_type: str | None = None,
    status: str | None = None,
    issue_date: str | None = None,
    expiration_date: str | None = None,
    issuing_board: str | None = None,
) -> HardExtractionCase:
    return HardExtractionCase(
        case_id=case_id,
        category=category,
        kind="license",
        description=description,
        pages=pages,
        expected_fields={
            "holder_name": holder_name,
            "license_number": license_number,
            "license_type": license_type,
            "status": status,
            "issue_date": issue_date,
            "expiration_date": expiration_date,
            "issuing_board": issuing_board,
        },
    )


def _coi(
    case_id: str,
    category: str,
    description: str,
    pages: tuple[tuple[str, ...], ...],
    *,
    insured_name: str | None = None,
    carrier: str | None = None,
    policy_number: str | None = None,
    effective_date: str | None = None,
    expiration_date: str | None = None,
    per_occurrence: str | None = None,
    aggregate: str | None = None,
) -> HardExtractionCase:
    return HardExtractionCase(
        case_id=case_id,
        category=category,
        kind="coi",
        description=description,
        pages=pages,
        expected_fields={
            "insured_name": insured_name,
            "carrier": carrier,
            "policy_number": policy_number,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "per_occurrence": per_occurrence,
            "aggregate": aggregate,
        },
    )


def _cv(
    case_id: str,
    category: str,
    description: str,
    pages: tuple[tuple[str, ...], ...],
    *,
    positions: tuple[dict[str, str | None], ...],
) -> HardExtractionCase:
    return HardExtractionCase(
        case_id=case_id,
        category=category,
        kind="cv",
        description=description,
        pages=pages,
        expected_positions=positions,
    )


def _noisy_layout_cases() -> list[HardExtractionCase]:
    return [
        _license(
            "noisy-1",
            "noisy_layout",
            "ALL-CAPS labels, '#' and dashes instead of colons",
            (
                (
                    "TEXAS LICENSED PROFESSIONAL COUNSELOR",
                    "HOLDER - Janelle Castillo",
                    "LIC # - LPC-700001",
                    "TYPE - LPC",
                    "STATUS - ACTIVE",
                    "ISSUED - 2019-03-10",
                    "EXPIRES - 2027-03-10",
                    "BOARD - Texas Behavioral Health Executive Council",
                ),
            ),
            holder_name="Janelle Castillo",
            license_number="LPC-700001",
            license_type="LPC",
            status="ACTIVE",
            issue_date="2019-03-10",
            expiration_date="2027-03-10",
            issuing_board="Texas Behavioral Health Executive Council",
        ),
        _license(
            "noisy-2",
            "noisy_layout",
            "label then value on the following line",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder Name:",
                    "Marcus Webb",
                    "License Number:",
                    "LPC-700002",
                    "Expiration Date:",
                    "2026-08-22",
                ),
            ),
            holder_name="Marcus Webb",
            license_number="LPC-700002",
            expiration_date="2026-08-22",
        ),
        _license(
            "noisy-3",
            "noisy_layout",
            "doubled/tabbed internal whitespace around labels",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder   Name:    Priya   Natarajan",
                    "License    Number:   LPC-700003",
                    "Status:     Active",
                ),
            ),
            holder_name="Priya Natarajan",
            license_number="LPC-700003",
            status="Active",
        ),
        _license(
            "noisy-4",
            "noisy_layout",
            "abbreviated, lowercase labels",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "hldr: Sarah O'Brien",
                    "lic.#: LPC-700004",
                    "iss: 2021-01-05",
                    "exp: 2027-01-05",
                ),
            ),
            holder_name="Sarah O'Brien",
            license_number="LPC-700004",
            issue_date="2021-01-05",
            expiration_date="2027-01-05",
        ),
        _coi(
            "noisy-5",
            "noisy_layout",
            "semicolon-separated single-line COI fields",
            (
                (
                    "Certificate of Malpractice Insurance",
                    "Insured: Devon Ashford ; Carrier: Lakeside Mutual Insurance ; "
                    "Policy#: POL-700005",
                ),
            ),
            insured_name="Devon Ashford",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700005",
        ),
    ]


def _narrative_cases() -> list[HardExtractionCase]:
    return [
        _license(
            "narrative-1",
            "narrative",
            "license facts embedded in a certifying sentence, no labels",
            (
                (
                    "This is to certify that Jane Anderson holds Texas license "
                    "number LPC-700010, type LPC, with active status. The license "
                    "was issued on 2018-06-01 and expires on 2026-06-01. Issuing "
                    "authority: Texas Behavioral Health Executive Council.",
                ),
            ),
            holder_name="Jane Anderson",
            license_number="LPC-700010",
            license_type="LPC",
            status="active",
            issue_date="2018-06-01",
            expiration_date="2026-06-01",
            issuing_board="Texas Behavioral Health Executive Council",
        ),
        _coi(
            "narrative-2",
            "narrative",
            "COI facts in one descriptive sentence, numerals",
            (
                (
                    "Certificate of Insurance: Policy POL-700011 is issued to Robert "
                    "Kim by Lakeside Mutual Insurance, effective 2025-01-01 through "
                    "2026-01-01, with a per-occurrence limit of $1,000,000 and an "
                    "aggregate limit of $3,000,000.",
                ),
            ),
            insured_name="Robert Kim",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700011",
            effective_date="2025-01-01",
            expiration_date="2026-01-01",
            per_occurrence="1000000",
            aggregate="3000000",
        ),
        _license(
            "narrative-3",
            "narrative",
            "name mentioned late in the sentence, passive voice",
            (
                (
                    "License number LPC-700012 (status: active, issuing board: "
                    "Texas Behavioral Health Executive Council) was granted to the "
                    "counselor Fatima Al-Rashid, effective 2022-09-15.",
                ),
            ),
            holder_name="Fatima Al-Rashid",
            license_number="LPC-700012",
            status="active",
            issuing_board="Texas Behavioral Health Executive Council",
            issue_date="2022-09-15",
        ),
        _coi(
            "narrative-4",
            "narrative",
            "insurance limits spelled out in words, not numerals",
            (
                (
                    "This confirms malpractice coverage for Yuki Tanaka under "
                    "policy POL-700013, carrier Lakeside Mutual Insurance, with "
                    "per-occurrence coverage of one million dollars and an "
                    "aggregate of three million dollars.",
                ),
            ),
            insured_name="Yuki Tanaka",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700013",
            per_occurrence="1000000",
            aggregate="3000000",
        ),
        _license(
            "narrative-5",
            "narrative",
            "spelled-out date, no ISO format anywhere in the text",
            (
                (
                    "Effective June 1, 2018, counselor Hannah Lindqvist was issued "
                    "Texas LPC license LPC-700014, expiring June 1, 2026.",
                ),
            ),
            holder_name="Hannah Lindqvist",
            license_number="LPC-700014",
            issue_date="2018-06-01",
            expiration_date="2026-06-01",
        ),
    ]


def _multi_page_cases() -> list[HardExtractionCase]:
    return [
        _license(
            "multipage-1",
            "multi_page",
            "identity on page 1, dates/board on page 2",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Omar Haddad",
                    "License number: LPC-700020",
                ),
                (
                    "Status: Active",
                    "Issue date: 2017-04-11",
                    "Expiration date: 2025-04-11",
                    "Issuing board: Texas Behavioral Health Executive Council",
                ),
            ),
            holder_name="Omar Haddad",
            license_number="LPC-700020",
            status="Active",
            issue_date="2017-04-11",
            expiration_date="2025-04-11",
            issuing_board="Texas Behavioral Health Executive Council",
        ),
        _license(
            "multipage-2",
            "multi_page",
            "cover page with no fields, fields entirely on page 2",
            (
                (
                    "Texas Behavioral Health Executive Council",
                    "License Verification Record",
                    "(see following page for details)",
                ),
                (
                    "Holder name: Beatrice Nwosu",
                    "License number: LPC-700021",
                    "License type: LPC",
                    "Status: Active",
                ),
            ),
            holder_name="Beatrice Nwosu",
            license_number="LPC-700021",
            license_type="LPC",
            status="Active",
        ),
        _coi(
            "multipage-3",
            "multi_page",
            "insured/carrier on page 1, limits on page 2",
            (
                (
                    "Certificate of Malpractice Insurance",
                    "Insured: Lucas Ferreira",
                    "Carrier: Lakeside Mutual Insurance",
                    "Policy number: POL-700022",
                ),
                (
                    "Effective date: 2025-02-01",
                    "Expiration date: 2026-02-01",
                    "Per occurrence: $100,000",
                    "Aggregate: $300,000",
                ),
            ),
            insured_name="Lucas Ferreira",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700022",
            effective_date="2025-02-01",
            expiration_date="2026-02-01",
            per_occurrence="100000",
            aggregate="300000",
        ),
        _license(
            "multipage-4",
            "multi_page",
            "three pages - identity, status, then dates/board",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Ingrid Solberg",
                    "License number: LPC-700023",
                ),
                ("Status: Active", "License type: LPC"),
                (
                    "Issue date: 2020-07-19",
                    "Expiration date: 2028-07-19",
                    "Issuing board: Texas Behavioral Health Executive Council",
                ),
            ),
            holder_name="Ingrid Solberg",
            license_number="LPC-700023",
            status="Active",
            license_type="LPC",
            issue_date="2020-07-19",
            expiration_date="2028-07-19",
            issuing_board="Texas Behavioral Health Executive Council",
        ),
        _coi(
            "multipage-5",
            "multi_page",
            "policy number repeated on both pages, limits only on page 2",
            (
                (
                    "Certificate of Malpractice Insurance",
                    "Policy number: POL-700024",
                    "Insured: Grace Mbeki",
                    "Carrier: Lakeside Mutual Insurance",
                ),
                (
                    "Policy number: POL-700024 (continued)",
                    "Per occurrence: $100,000",
                    "Aggregate: $300,000",
                    "Effective date: 2025-05-01",
                ),
            ),
            insured_name="Grace Mbeki",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700024",
            per_occurrence="100000",
            aggregate="300000",
            effective_date="2025-05-01",
        ),
    ]


def _unusual_cv_cases() -> list[HardExtractionCase]:
    return [
        _cv(
            "cvformat-1",
            "unusual_cv",
            "bulleted work history, title/employer on one bullet line",
            (
                (
                    "Curriculum Vitae",
                    "Name: Theo Kowalski",
                    "Work History:",
                    "• Associate Counselor, Riverside Behavioral Health (2019-02-01 to 2022-02-01)",
                    "• Licensed Professional Counselor, Brightpath Counseling Group "
                    "(2022-02-01 to present)",
                ),
            ),
            positions=(
                {
                    "title": "Associate Counselor",
                    "employer": "Riverside Behavioral Health",
                    "start": "2019-02-01",
                    "end": "2022-02-01",
                },
                {
                    "title": "Licensed Professional Counselor",
                    "employer": "Brightpath Counseling Group",
                    "start": "2022-02-01",
                    "end": None,
                },
            ),
        ),
        _cv(
            "cvformat-2",
            "unusual_cv",
            "employer stated before title, em-dash separator",
            (
                (
                    "Curriculum Vitae",
                    "Name: Camille Dupont",
                    "Experience:",
                    "Riverside Behavioral Health — Associate Counselor (2018-03-01 - 2021-03-01)",
                ),
            ),
            positions=(
                {
                    "title": "Associate Counselor",
                    "employer": "Riverside Behavioral Health",
                    "start": "2018-03-01",
                    "end": "2021-03-01",
                },
            ),
        ),
        _cv(
            "cvformat-3",
            "unusual_cv",
            "abbreviated month names in the date range",
            (
                (
                    "Curriculum Vitae",
                    "Name: Aiden Novak",
                    "Licensed Professional Counselor, Brightpath Counseling Group "
                    "(Jan 2020 - Mar 2023)",
                ),
            ),
            positions=(
                {
                    "title": "Licensed Professional Counselor",
                    "employer": "Brightpath Counseling Group",
                    "start": "2020-01-01",
                    "end": "2023-03-01",
                },
            ),
        ),
        _cv(
            "cvformat-4",
            "unusual_cv",
            "two positions on one line separated by a semicolon",
            (
                (
                    "Curriculum Vitae",
                    "Name: Rosalind Achebe",
                    "Associate Counselor, Riverside Behavioral Health "
                    "(2017-06-01 - 2019-06-01); Licensed Professional Counselor, "
                    "Brightpath Counseling Group (2019-06-01 - present)",
                ),
            ),
            positions=(
                {
                    "title": "Associate Counselor",
                    "employer": "Riverside Behavioral Health",
                    "start": "2017-06-01",
                    "end": "2019-06-01",
                },
                {
                    "title": "Licensed Professional Counselor",
                    "employer": "Brightpath Counseling Group",
                    "start": "2019-06-01",
                    "end": None,
                },
            ),
        ),
        _cv(
            "cvformat-5",
            "unusual_cv",
            "ongoing position described as 'current' instead of 'present'",
            (
                (
                    "Curriculum Vitae",
                    "Name: Mei Lin Tanaka",
                    "Licensed Professional Counselor at Brightpath Counseling Group, "
                    "2021-05-01 to current.",
                ),
            ),
            positions=(
                {
                    "title": "Licensed Professional Counselor",
                    "employer": "Brightpath Counseling Group",
                    "start": "2021-05-01",
                    "end": None,
                },
            ),
        ),
    ]


def _ambiguous_date_cases() -> list[HardExtractionCase]:
    return [
        _license(
            "ambigdate-1",
            "ambiguous_date",
            "bare MM/DD/YYYY, both day and month <=12 (genuinely ambiguous)",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Elena Vasquez",
                    "License number: LPC-700030",
                    "Issue date: 03/04/2020",
                    "Expiration date: 03/04/2028",
                ),
            ),
            holder_name="Elena Vasquez",
            license_number="LPC-700030",
            issue_date="2020-03-04",
            expiration_date="2028-03-04",
        ),
        _license(
            "ambigdate-2",
            "ambiguous_date",
            "bare MM/DD/YYYY, day >12 (unambiguous control case)",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Tobias Reinholt",
                    "License number: LPC-700031",
                    "Issue date: 04/15/2020",
                    "Expiration date: 04/15/2028",
                ),
            ),
            holder_name="Tobias Reinholt",
            license_number="LPC-700031",
            issue_date="2020-04-15",
            expiration_date="2028-04-15",
        ),
        _coi(
            "ambigdate-3",
            "ambiguous_date",
            "ambiguous effective/expiration dates on a COI",
            (
                (
                    "Certificate of Malpractice Insurance",
                    "Insured: Nadia Petrov",
                    "Carrier: Lakeside Mutual Insurance",
                    "Policy number: POL-700032",
                    "Effective date: 02/03/2025",
                    "Expiration date: 02/03/2026",
                ),
            ),
            insured_name="Nadia Petrov",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700032",
            effective_date="2025-02-03",
            expiration_date="2026-02-03",
        ),
        _license(
            "ambigdate-4",
            "ambiguous_date",
            "one ambiguous date, one unambiguous date in the same document",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Samuel Okonkwo",
                    "License number: LPC-700033",
                    "Issue date: 07/09/2019",
                    "Expiration date: 11/21/2027",
                ),
            ),
            holder_name="Samuel Okonkwo",
            license_number="LPC-700033",
            issue_date="2019-07-09",
            expiration_date="2027-11-21",
        ),
        _coi(
            "ambigdate-5",
            "ambiguous_date",
            "day-first-looking date written with dots instead of slashes",
            (
                (
                    "Certificate of Malpractice Insurance",
                    "Insured: Clara Dubois",
                    "Carrier: Lakeside Mutual Insurance",
                    "Policy number: POL-700034",
                    "Effective date: 01.06.2025",
                ),
            ),
            insured_name="Clara Dubois",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700034",
            # "01.06.2025" has no dot-separated format in
            # app/core/normalize.py's _DATE_FORMATS - expected to come
            # back unknown, a genuine (not simulated) parser gap this
            # case is designed to surface.
            effective_date=None,
        ),
    ]


def _name_suffix_cases() -> list[HardExtractionCase]:
    return [
        _license(
            "suffix-1",
            "name_suffix",
            "credential suffix attached to the holder name",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Jane Doe, LPC-S",
                    "License number: LPC-700040",
                ),
            ),
            holder_name="Jane Doe, LPC-S",
            license_number="LPC-700040",
        ),
        _license(
            "suffix-2",
            "name_suffix",
            "generational suffix (Jr.)",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: John Smith Jr.",
                    "License number: LPC-700041",
                ),
            ),
            holder_name="John Smith Jr.",
            license_number="LPC-700041",
        ),
        _license(
            "suffix-3",
            "name_suffix",
            "title prefix plus academic suffix",
            (
                (
                    "Texas Licensed Professional Counselor",
                    "Holder name: Dr. Maria Garcia-Lopez, Ph.D.",
                    "License number: LPC-700042",
                ),
            ),
            holder_name="Dr. Maria Garcia-Lopez, Ph.D.",
            license_number="LPC-700042",
        ),
        _coi(
            "suffix-4",
            "name_suffix",
            "suffix on the insured name of a COI",
            (
                (
                    "Certificate of Malpractice Insurance",
                    "Insured: Michael O'Connell III",
                    "Carrier: Lakeside Mutual Insurance",
                    "Policy number: POL-700043",
                ),
            ),
            insured_name="Michael O'Connell III",
            carrier="Lakeside Mutual Insurance",
            policy_number="POL-700043",
        ),
        _cv(
            "suffix-5",
            "name_suffix",
            "suffix on the cv's own name line",
            (
                (
                    "Curriculum Vitae",
                    "Name: Angela Whitfield, LPC",
                    "Licensed Professional Counselor, Brightpath Counseling Group "
                    "(2020-01-01 - present)",
                ),
            ),
            positions=(
                {
                    "title": "Licensed Professional Counselor",
                    "employer": "Brightpath Counseling Group",
                    "start": "2020-01-01",
                    "end": None,
                },
            ),
        ),
    ]


def all_cases() -> list[HardExtractionCase]:
    return [
        *_noisy_layout_cases(),
        *_narrative_cases(),
        *_multi_page_cases(),
        *_unusual_cv_cases(),
        *_ambiguous_date_cases(),
        *_name_suffix_cases(),
    ]


def generate_hard_extraction_set(output_root: Path) -> list[dict[str, Any]]:
    """Renders every case to `output_root/hard_extraction/<case_id>.pdf`
    and returns the ground-truth manifest (one entry per case) that
    app/eval/hard_extract_run.py scores against."""
    manifest: list[dict[str, Any]] = []
    for case in all_cases():
        rel_path = f"hard_extraction/{case.case_id}.pdf"
        _render(output_root / rel_path, case)
        manifest.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "kind": case.kind,
                "description": case.description,
                "path": rel_path,
                "expected_fields": case.expected_fields,
                "expected_positions": list(case.expected_positions),
            }
        )
    return manifest


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import json

    repo_root = Path(__file__).resolve().parents[4]
    output_root = repo_root / "eval" / "fixtures"
    manifest = generate_hard_extraction_set(output_root)
    manifest_path = output_root / "hard_extraction_ground_truth.json"
    manifest_path.write_text(json.dumps({"cases": manifest}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(manifest)} cases to {manifest_path}")


if __name__ == "__main__":  # pragma: no cover
    main()

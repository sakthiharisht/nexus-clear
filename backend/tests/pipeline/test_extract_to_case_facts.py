from __future__ import annotations

from datetime import date

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    CvPositionExtraction,
    ExtractedField,
    LicenseExtraction,
)
from app.pipeline.extract_to_case_facts import (
    apply_coi_extraction,
    apply_cv_extraction,
    apply_license_extraction,
)
from app.rules.context import CaseFacts

LICENSE_TEXT = (
    "Holder name: Jane Doe\n"
    "License number: LPC-12345\n"
    "Expiration date: 2026-01-01\n"
)


def _field(value: str, quote: str) -> ExtractedField:
    return ExtractedField(value=value, confidence=0.9, page=1, quote=quote)


def _base_facts() -> CaseFacts:
    return CaseFacts(target_date=date(2026, 1, 1))


def test_apply_license_extraction_projects_verified_fields() -> None:
    raw = LicenseExtraction(
        holder_name=_field("Jane Doe", "Holder name: Jane Doe"),
        license_number=_field("LPC-12345", "License number: LPC-12345"),
        expiration_date=_field("2026-01-01", "Expiration date: 2026-01-01"),
    )
    facts = apply_license_extraction(_base_facts(), "doc-license", raw, LICENSE_TEXT)
    assert facts.license.doc_id == "doc-license"
    assert facts.license.holder_name == "Jane Doe"
    assert facts.license.license_number == "LPC-12345"
    assert facts.license.expiration_date == date(2026, 1, 1)


def test_apply_license_extraction_leaves_a_hallucinated_field_as_none() -> None:
    raw = LicenseExtraction(holder_name=_field("John Smith", "Holder name: John Smith"))
    facts = apply_license_extraction(_base_facts(), "doc-license", raw, LICENSE_TEXT)
    assert facts.license.holder_name is None


def test_apply_license_extraction_does_not_mutate_the_input_facts() -> None:
    original = _base_facts()
    raw = LicenseExtraction(holder_name=_field("Jane Doe", "Holder name: Jane Doe"))
    apply_license_extraction(original, "doc-license", raw, LICENSE_TEXT)
    assert original.license.holder_name is None


def test_apply_coi_extraction_projects_money_as_floats() -> None:
    doc_text = "Per occurrence: $1,000,000.00\nAggregate: $3,000,000.00"
    raw = CoiExtraction(
        per_occurrence=_field("$1,000,000.00", "Per occurrence: $1,000,000.00"),
        aggregate=_field("$3,000,000.00", "Aggregate: $3,000,000.00"),
    )
    facts = apply_coi_extraction(_base_facts(), "doc-coi", raw, doc_text)
    assert facts.coi.per_occurrence == 1_000_000.0
    assert facts.coi.aggregate == 3_000_000.0


def test_apply_cv_extraction_projects_positions_only() -> None:
    doc_text = "Counselor, Acme Clinic (2020-01-01 - present)"
    raw = CvExtraction(
        positions=[
            CvPositionExtraction(
                title=_field("Counselor", "Counselor"),
                employer=_field("Acme Clinic", "Acme Clinic"),
                start=_field("2020-01-01", "2020-01-01"),
            )
        ]
    )
    facts = apply_cv_extraction(_base_facts(), "doc-cv", raw, doc_text)
    assert facts.cv.doc_id == "doc-cv"
    assert len(facts.cv.positions) == 1
    assert facts.cv.positions[0].title == "Counselor"
    assert facts.cv.positions[0].end is None

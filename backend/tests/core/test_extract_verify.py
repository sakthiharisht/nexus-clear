from __future__ import annotations

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    CvPositionExtraction,
    EducationExtraction,
    ExtractedField,
    LicenseExtraction,
    W9Extraction,
)
from app.core.extract_verify import (
    verify_coi_extraction,
    verify_cv_extraction,
    verify_education_extraction,
    verify_license_extraction,
    verify_w9_extraction,
)

LICENSE_TEXT = (
    "Holder name: Jane Doe\n"
    "License number: LPC-12345\n"
    "License type: LPC\n"
    "Status: active\n"
    "Issue date: 2020-01-01\n"
    "Expiration date: 2026-01-01\n"
    "Issuing board: Texas Behavioral Health Executive Council\n"
)


def _field(value: str, quote: str) -> ExtractedField:
    return ExtractedField(value=value, confidence=0.9, page=1, quote=quote)


def test_verify_license_extraction_all_fields_known_and_verified() -> None:
    raw = LicenseExtraction(
        holder_name=_field("Jane Doe", "Holder name: Jane Doe"),
        license_number=_field("LPC-12345", "License number: LPC-12345"),
        license_type=_field("LPC", "License type: LPC"),
        status=_field("active", "Status: active"),
        issue_date=_field("2020-01-01", "Issue date: 2020-01-01"),
        expiration_date=_field("2026-01-01", "Expiration date: 2026-01-01"),
        issuing_board=_field(
            "Texas Behavioral Health Executive Council",
            "Issuing board: Texas Behavioral Health Executive Council",
        ),
    )
    verified = verify_license_extraction(raw, LICENSE_TEXT)
    assert all(f.status == "known" for f in verified.values())
    assert all(f.quote_verified for f in verified.values())
    assert verified["expiration_date"].value == "2026-01-01"


def test_verify_license_extraction_demotes_a_hallucinated_field() -> None:
    raw = LicenseExtraction(holder_name=_field("John Smith", "Holder name: John Smith"))
    verified = verify_license_extraction(raw, LICENSE_TEXT)
    assert verified["holder_name"].status == "unknown"


def test_verify_coi_extraction_normalizes_money() -> None:
    doc_text = "Per occurrence: $1,000,000.00\nAggregate: $3,000,000.00"
    raw = CoiExtraction(
        per_occurrence=_field("$1,000,000.00", "Per occurrence: $1,000,000.00"),
        aggregate=_field("$3,000,000.00", "Aggregate: $3,000,000.00"),
    )
    verified = verify_coi_extraction(raw, doc_text)
    assert verified["per_occurrence"].value == "1000000.0"
    assert verified["aggregate"].value == "3000000.0"


def test_verify_cv_extraction_verifies_positions_and_education_lists() -> None:
    doc_text = (
        "Name: Jane Doe\nCounselor, Acme Clinic (2020-01-01 - present)\n"
        "MA Counseling, State University"
    )
    raw = CvExtraction(
        name=_field("Jane Doe", "Name: Jane Doe"),
        positions=[
            CvPositionExtraction(
                title=_field("Counselor", "Counselor"),
                employer=_field("Acme Clinic", "Acme Clinic"),
                start=_field("2020-01-01", "2020-01-01"),
            )
        ],
        education=[_field("MA Counseling, State University", "MA Counseling, State University")],
    )
    verified = verify_cv_extraction(raw, doc_text)
    assert verified["name"].status == "known"
    assert verified["positions"][0]["title"].value == "Counselor"
    assert verified["positions"][0]["end"].status == "unknown"  # no end field was supplied
    assert verified["education"][0].status == "known"


def test_verify_education_extraction() -> None:
    doc_text = (
        "Name: Jane Doe\nDegree: MA Counseling\nInstitution: State University\nDate: 2015-05-01"
    )
    raw = EducationExtraction(
        name=_field("Jane Doe", "Name: Jane Doe"),
        degree=_field("MA Counseling", "Degree: MA Counseling"),
        institution=_field("State University", "Institution: State University"),
        date=_field("2015-05-01", "Date: 2015-05-01"),
    )
    verified = verify_education_extraction(raw, doc_text)
    assert verified["degree"].status == "known"
    assert verified["date"].value == "2015-05-01"


def test_verify_w9_extraction_normalizes_booleans() -> None:
    doc_text = "TIN present: yes\nSigned: no"
    raw = W9Extraction(
        tin_present=_field("yes", "TIN present: yes"),
        signed=_field("no", "Signed: no"),
    )
    verified = verify_w9_extraction(raw, doc_text)
    assert verified["tin_present"].value == "true"
    assert verified["signed"].value == "false"


def test_verify_license_extraction_image_marks_known_but_unverified() -> None:
    raw = LicenseExtraction(holder_name=_field("Jane Doe", "Holder name: Jane Doe"))
    verified = verify_license_extraction(raw, None)
    assert verified["holder_name"].status == "known"
    assert verified["holder_name"].quote_verified is False

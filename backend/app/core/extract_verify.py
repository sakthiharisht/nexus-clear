"""Per-doc-type citation verification (SPEC.md section 7.3), built on
the field-level primitives in app/core/citations.py. One function per
extraction schema, each returning a plain dict[str, VerifiedField] (or,
for cv's list fields, a list of such dicts) keyed by the schema's own
field names - callers that feed CaseFacts (app/backends/
extract_to_case_facts.py) read specific keys back out; callers that
only need field-level accuracy for the eval report can iterate the
whole dict uniformly.
"""

from __future__ import annotations

from typing import TypedDict

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    EducationExtraction,
    LicenseExtraction,
    VerifiedField,
    W9Extraction,
)
from app.core.citations import (
    verify_bool_field,
    verify_date_field,
    verify_money_field,
    verify_name_field,
    verify_text_field,
)


class VerifiedCvPosition(TypedDict):
    title: VerifiedField
    employer: VerifiedField
    start: VerifiedField
    end: VerifiedField


class VerifiedCv(TypedDict):
    name: VerifiedField
    positions: list[VerifiedCvPosition]
    education: list[VerifiedField]


def verify_license_extraction(
    raw: LicenseExtraction, document_text: str | None
) -> dict[str, VerifiedField]:
    return {
        "holder_name": verify_name_field(raw.holder_name, document_text),
        "license_number": verify_text_field(raw.license_number, document_text),
        "license_type": verify_text_field(raw.license_type, document_text),
        "status": verify_text_field(raw.status, document_text),
        "issue_date": verify_date_field(raw.issue_date, document_text),
        "expiration_date": verify_date_field(raw.expiration_date, document_text),
        "issuing_board": verify_text_field(raw.issuing_board, document_text),
    }


def verify_coi_extraction(
    raw: CoiExtraction, document_text: str | None
) -> dict[str, VerifiedField]:
    return {
        "insured_name": verify_name_field(raw.insured_name, document_text),
        "carrier": verify_text_field(raw.carrier, document_text),
        "policy_number": verify_text_field(raw.policy_number, document_text),
        "effective_date": verify_date_field(raw.effective_date, document_text),
        "expiration_date": verify_date_field(raw.expiration_date, document_text),
        "per_occurrence": verify_money_field(raw.per_occurrence, document_text),
        "aggregate": verify_money_field(raw.aggregate, document_text),
    }


def verify_cv_extraction(raw: CvExtraction, document_text: str | None) -> VerifiedCv:
    return VerifiedCv(
        name=verify_name_field(raw.name, document_text),
        positions=[
            VerifiedCvPosition(
                title=verify_text_field(position.title, document_text),
                employer=verify_text_field(position.employer, document_text),
                start=verify_date_field(position.start, document_text),
                end=verify_date_field(position.end, document_text),
            )
            for position in raw.positions
        ],
        education=[verify_text_field(entry, document_text) for entry in raw.education],
    )


def verify_education_extraction(
    raw: EducationExtraction, document_text: str | None
) -> dict[str, VerifiedField]:
    return {
        "name": verify_name_field(raw.name, document_text),
        "degree": verify_text_field(raw.degree, document_text),
        "institution": verify_text_field(raw.institution, document_text),
        "date": verify_date_field(raw.date, document_text),
    }


def verify_w9_extraction(raw: W9Extraction, document_text: str | None) -> dict[str, VerifiedField]:
    return {
        "name": verify_name_field(raw.name, document_text),
        "business_name": verify_text_field(raw.business_name, document_text),
        "tin_present": verify_bool_field(raw.tin_present, document_text),
        "signed": verify_bool_field(raw.signed, document_text),
    }

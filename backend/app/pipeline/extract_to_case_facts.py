"""Projects verified Extract output (app/core/extract_verify.py) into
CaseFacts (SPEC.md section 7.3: "Feed extracted values into CaseFacts
for the rules engine; code still decides pass/fail").

Scope boundary, not a bug: CaseFacts (app/rules/context.py) has no
slot for cv.name, cv.education, or a standalone education/w9 schema -
no rule in rules/tx_bcbstx_lpc.yaml reads any of those (education is
only a required_slot presence/legibility check; there's no
R-*-"has a degree" rule). Those two extraction kinds are built and
citation-verified like the other three (SPEC 7.3 lists all 5 schemas
literally), but have nothing to project here. If a future rule needs
them, CaseFacts gains the field then - not speculatively now.

A `VerifiedField` with status="unknown" always projects to None here,
never a guessed value (CLAUDE.md invariant 2) - this is the one place
Extract's output actually reaches the rules engine's input, so it's
the last chance to enforce that.
"""

from __future__ import annotations

from datetime import date

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    LicenseExtraction,
    VerifiedField,
)
from app.core.extract_verify import (
    verify_coi_extraction,
    verify_cv_extraction,
    verify_license_extraction,
)
from app.rules.context import CaseFacts, CoiFacts, CvFacts, CvPosition, LicenseFacts


def _str_value(field: VerifiedField) -> str | None:
    return field.value if field.status == "known" else None


def _date_value(field: VerifiedField) -> date | None:
    if field.status != "known" or field.value is None:
        return None
    return date.fromisoformat(field.value)


def _float_value(field: VerifiedField) -> float | None:
    if field.status != "known" or field.value is None:
        return None
    return float(field.value)


def apply_license_extraction(
    facts: CaseFacts, doc_id: str, raw: LicenseExtraction, document_text: str | None
) -> CaseFacts:
    verified = verify_license_extraction(raw, document_text)
    return facts.model_copy(
        update={
            "license": LicenseFacts(
                doc_id=doc_id,
                holder_name=_str_value(verified["holder_name"]),
                license_number=_str_value(verified["license_number"]),
                license_type=_str_value(verified["license_type"]),
                status=_str_value(verified["status"]),
                issue_date=_date_value(verified["issue_date"]),
                expiration_date=_date_value(verified["expiration_date"]),
                issuing_board=_str_value(verified["issuing_board"]),
            )
        }
    )


def apply_coi_extraction(
    facts: CaseFacts, doc_id: str, raw: CoiExtraction, document_text: str | None
) -> CaseFacts:
    verified = verify_coi_extraction(raw, document_text)
    return facts.model_copy(
        update={
            "coi": CoiFacts(
                doc_id=doc_id,
                insured_name=_str_value(verified["insured_name"]),
                carrier=_str_value(verified["carrier"]),
                policy_number=_str_value(verified["policy_number"]),
                effective_date=_date_value(verified["effective_date"]),
                expiration_date=_date_value(verified["expiration_date"]),
                per_occurrence=_float_value(verified["per_occurrence"]),
                aggregate=_float_value(verified["aggregate"]),
            )
        }
    )


def apply_cv_extraction(
    facts: CaseFacts, doc_id: str, raw: CvExtraction, document_text: str | None
) -> CaseFacts:
    """Only `positions` projects into CaseFacts.cv - see module
    docstring for why `name`/`education` don't."""
    verified = verify_cv_extraction(raw, document_text)
    positions = [
        CvPosition(
            title=_str_value(p["title"]),
            employer=_str_value(p["employer"]),
            start=_date_value(p["start"]),
            end=_date_value(p["end"]),
        )
        for p in verified["positions"]
    ]
    return facts.model_copy(update={"cv": CvFacts(doc_id=doc_id, positions=positions)})

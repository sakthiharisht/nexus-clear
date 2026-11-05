"""CAQH-style packet (SPEC.md section 7.9): a prefilled profile
assembled from verified fields only (CLAUDE.md invariant 2 - an
`unknown` field is omitted, never a guess or a blank placeholder).
Reads app/core/orm.py's Extraction rows (the verified field dict
app/orchestrator/run.py persists per document) rather than parsing a
Finding's free-text evidence quote, which was never meant to be
machine-read back out.

Labeled "CAQH-style" deliberately: the real CAQH/DataSpring schema is
not verified here, so this never claims compatibility with it (SPEC
7.9 / README caveat) - it is not, and must never become, a submission
to any payer or portal (CLAUDE.md invariant 5).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.orm import Extraction

PACKET_LABEL = "CAQH-style profile - not a CAQH/DataSpring submission"

_DOCUMENT_SCHEMAS = ("license", "coi", "cv")


class CaqhStep(BaseModel):
    """One deterministic, static item this app never fills in and never
    claims to - not derived from any case data, so it's identical on
    every packet. needs_verification is always True here: the list
    itself (which CAQH sections exist, and that authorization is
    separate from attestation) is sourced from Carepatron's published
    guidance, not CAQH's or BCBSTX's own documentation (M9.1 #3/#4;
    verified live against
    https://www.carepatron.com/blog/what-is-caqh-and-how-to-set-it-up)."""

    description: str
    source_id: str = "carepatron_caqh_guide"
    needs_verification: bool = True


# M9.1 #3 (payer authorization) + #4 (what the packet doesn't cover):
# this app only ever reads license/COI/CV/education/W9 documents - a
# real CAQH profile has several other sections, and access control
# separate from the profile's own completeness, that nothing here
# touches. Order follows the CAQH ProView flow: authorize first (a
# payer can't see a profile at all without it, complete or not), then
# the sections this app doesn't collect, then attest last.
STILL_TO_DO_IN_CAQH: list[CaqhStep] = [
    CaqhStep(
        description=(
            "Authorize the payer(s) you're credentialing with to access your CAQH profile - "
            "without this, a payer can't see your data even if the profile is complete."
        )
    ),
    CaqhStep(description="Complete practice locations (not collected by this app)."),
    CaqhStep(description="Complete hospital affiliations (not collected by this app)."),
    CaqhStep(description="Answer the disclosure questions (not collected by this app)."),
    CaqhStep(description="List your specialties (not collected by this app)."),
    CaqhStep(description="Add professional references (not collected by this app)."),
    CaqhStep(
        description="Add board certifications, if applicable (not collected by this app)."
    ),
    CaqhStep(
        description=(
            "Attest inside CAQH - your profile is not active and complete until you do, and "
            "CAQH requires periodic re-attestation afterward. This app's own confirmation step "
            "is not CAQH attestation."
        )
    ),
]


class CaqhStylePacket(BaseModel):
    case_id: UUID
    label: str = PACKET_LABEL
    profile: dict[str, object]
    license: dict[str, object] = {}
    coi: dict[str, object] = {}
    cv: dict[str, object] = {}
    still_to_do_in_caqh: list[CaqhStep] = STILL_TO_DO_IN_CAQH


def _verified_value(field: object) -> tuple[bool, object]:
    if not isinstance(field, dict) or field.get("status") != "known":
        return False, None
    return True, field.get("value")


def _verified_flat_fields(fields: dict[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, field in fields.items():
        known, value = _verified_value(field)
        if known:
            result[name] = value
    return result


def _verified_cv_fields(fields: dict[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    known, value = _verified_value(fields.get("name"))
    if known:
        result["name"] = value

    positions = fields.get("positions")
    verified_positions: list[dict[str, object]] = []
    if isinstance(positions, list):
        for position in positions:
            if not isinstance(position, dict):
                continue
            verified_position = _verified_flat_fields(position)
            if verified_position:
                verified_positions.append(verified_position)
    if verified_positions:
        result["positions"] = verified_positions
    return result


def build_packet(
    case_id: UUID, *, provider_profile: dict[str, object], extractions: list[Extraction]
) -> CaqhStylePacket:
    by_schema: dict[str, dict[str, object]] = {schema: {} for schema in _DOCUMENT_SCHEMAS}
    for extraction in extractions:
        if extraction.schema_version not in by_schema:
            continue
        if extraction.schema_version == "cv":
            verified = _verified_cv_fields(extraction.fields)
        else:
            verified = _verified_flat_fields(extraction.fields)
        by_schema[extraction.schema_version].update(verified)

    return CaqhStylePacket(
        case_id=case_id,
        profile=provider_profile,
        license=by_schema["license"],
        coi=by_schema["coi"],
        cv=by_schema["cv"],
    )

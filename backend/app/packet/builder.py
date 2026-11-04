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


class CaqhStylePacket(BaseModel):
    case_id: UUID
    label: str = PACKET_LABEL
    profile: dict[str, object]
    license: dict[str, object] = {}
    coi: dict[str, object] = {}
    cv: dict[str, object] = {}


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

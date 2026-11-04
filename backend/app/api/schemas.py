"""Request/response models for the intake API (SPEC.md section 8) — a
stage boundary like every other (CLAUDE.md: "Pydantic models at every
stage boundary"), distinct from both the ORM models (app/core/orm.py) and
the rules engine's CaseFacts (app/rules/context.py).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.contracts import Finding


class CreateCaseRequest(BaseModel):
    payer: str
    provider_type: str
    provider_profile: dict[str, object]
    # Defaults to today + the rule pack's target_date_default_offset_days
    # if omitted (SPEC.md section 6).
    target_date: date | None = None


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payer: str
    provider_type: str
    provider_profile: dict[str, object]
    target_date: date
    state: str
    created_at: datetime


class ChecklistSlot(BaseModel):
    slot: str
    doc_type: str
    required: bool
    needs_verification: bool
    uploaded: bool
    document_id: UUID | None = None


class ChecklistResponse(BaseModel):
    case_id: UUID
    slots: list[ChecklistSlot]
    missing_required_slots: list[str]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    slot: str
    sha256: str
    uploaded_at: datetime


class ReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    finding_id: UUID
    status: str
    reviewer_resolution: dict[str, object] | None
    created_at: datetime
    resolved_at: datetime | None


class ReviewItemDetailResponse(ReviewItemResponse):
    # The full Finding (evidence quote + doc page, or registry record)
    # this review item is about - SPEC.md section 7.9: "view evidence".
    finding: Finding


class AttestRequest(BaseModel):
    # Required and must be exactly `true` - omitting it, or sending
    # `false`, fails Pydantic validation before the route body even
    # runs (SPEC.md section 7.9: an explicit provider confirmation,
    # never implied by merely calling the endpoint).
    confirmed: Literal[True]
    attested_by: str
    typed_name: str


class AttestResponse(BaseModel):
    case_id: UUID
    attested_by: str
    attested_at: datetime
    packet_hash: str


ReviewDecision = Literal["confirm", "override", "needs_more_info"]


class ResolveReviewRequest(BaseModel):
    decision: ReviewDecision
    note: str
    resolved_by: str
    # Required when decision == "override" - the human's corrected
    # status (CLAUDE.md invariant 1 still holds: the model never set
    # this, a named human reviewer did, recorded as decided_by="human").
    override_status: Literal["pass", "fail", "not_applicable", "unknown"] | None = None

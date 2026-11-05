"""Request/response models for the intake API (SPEC.md section 8) — a
stage boundary like every other (CLAUDE.md: "Pydantic models at every
stage boundary"), distinct from both the ORM models (app/core/orm.py) and
the rules engine's CaseFacts (app/rules/context.py).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts import Finding


class ProviderProfile(BaseModel):
    """Pre-M9 fix #3: a typed intake profile instead of an opaque dict -
    rejects a missing legal_name/npi or any unrecognized key at the API
    boundary, rather than letting a typo or a wrong field name through
    to silently resolve as `unknown` three stages later
    (app/rules/context.py's ProfileFacts/SupervisionFacts, which this
    model's fields line up with directly - app/orchestrator/run.py
    reads them back out of the stored dict the same way either way).
    """

    model_config = ConfigDict(extra="forbid")

    legal_name: str
    npi: str
    practice_name: str | None = None
    supervisor_count: int | None = None
    supervisor_license_number: str | None = None


class CreateCaseRequest(BaseModel):
    payer: str
    provider_type: str
    provider_profile: ProviderProfile
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


class CaseCreatedResponse(CaseResponse):
    # Pre-M9 fix #4: returned only here, once, at creation - never
    # re-exposed by GET /cases/{id} (CaseResponse itself has no such
    # field). The caller must save it; there is no recovery endpoint,
    # same as any other demo-grade bearer token.
    provider_token: str


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


class GapExplanationRequest(BaseModel):
    # M9.1 #5: untrusted free text (CLAUDE.md invariant 3 - same
    # standing as document text), length-limited at the API boundary.
    gap_start: date
    gap_end: date
    explanation: str = Field(min_length=1, max_length=1000)


class GapExplanationResponse(BaseModel):
    gap_start: date
    gap_end: date
    explanation: str
    # Deterministic scanner result (app/core/injection.py), computed at
    # submission time and never re-derived from a model - same
    # invariant as R-SEC-001's own injection_flag finding.
    injection_detected: bool
    submitted_at: datetime


class ReviewItemDetailResponse(ReviewItemResponse):
    # The full Finding (evidence quote + doc page, or registry record)
    # this review item is about - SPEC.md section 7.9: "view evidence".
    finding: Finding
    # Present only when this item's underlying rule is the work-history
    # gap check and the provider has submitted an explanation for it
    # (M9.1 #5) - shown to the reviewer alongside the finding, never
    # auto-resolving it.
    gap_explanation: GapExplanationResponse | None = None


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


class AuditLogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ts: datetime
    actor: str
    action: str
    case_id: UUID | None
    object_ref: str | None
    detail: dict[str, object] | None

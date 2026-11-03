"""Request/response models for the intake API (SPEC.md section 8) — a
stage boundary like every other (CLAUDE.md: "Pydantic models at every
stage boundary"), distinct from both the ORM models (app/core/orm.py) and
the rules engine's CaseFacts (app/rules/context.py).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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

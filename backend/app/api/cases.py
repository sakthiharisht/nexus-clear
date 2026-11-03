"""Intake API (SPEC.md section 8): create a case, list its checklist
(required slots from the rule pack, cross-referenced against what's been
uploaded), and upload a document into a slot.

Required-slot *presence* (which slots are missing) is computed here, at
the API layer, not as a rule-pack rule — none of the 14 rule kinds cover
"is every required slot filled" (see the M1 completion report), and
that's intentional: it's an intake/checklist concern that has to run
before Validate even has documents to evaluate, not a credentialing-
content judgment the rules engine makes.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_blob_store, get_key_manager, get_rule_pack, get_session
from app.api.schemas import (
    CaseResponse,
    ChecklistResponse,
    ChecklistSlot,
    CreateCaseRequest,
    DocumentResponse,
)
from app.core.config import settings
from app.core.orm import Case, Document
from app.rules.schema import RulePack
from app.vault import service
from app.vault.blob_store import BlobStore
from app.vault.key_manager import KeyManager

router = APIRouter(prefix="/cases", tags=["cases"])

# SPEC.md section 7.1: "Accept PDF/PNG/JPG ... magic-byte check" — the
# actual file content is sniffed, not the client-supplied Content-Type or
# filename extension, neither of which can be trusted.
_MAGIC_BYTES: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}


def _sniff_content_type(content: bytes) -> str | None:
    for mime, magic in _MAGIC_BYTES.items():
        if content.startswith(magic):
            return mime
    return None


def _get_case_or_404(session: Session, case_id: UUID) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"case {case_id} not found")
    return case


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(
    body: CreateCaseRequest,
    session: Session = Depends(get_session),
    pack: RulePack = Depends(get_rule_pack),
    key_manager: KeyManager = Depends(get_key_manager),
) -> Case:
    # A provider starting a case today reasonably defaults their target
    # date off today — this is ordinary request-time wall-clock use, not
    # the rules engine (CLAUDE.md's "no now()" invariant is scoped to
    # app/rules/*, which always takes an explicit as_of instead).
    target_date = body.target_date or (
        date.today() + timedelta(days=pack.target_date_default_offset_days)
    )
    case = Case(
        payer=body.payer,
        provider_type=body.provider_type,
        provider_profile=body.provider_profile,
        target_date=target_date,
        wrapped_data_key=service.create_wrapped_case_key(key_manager),
    )
    session.add(case)
    session.commit()
    session.refresh(case)
    return case


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(case_id: UUID, session: Session = Depends(get_session)) -> Case:
    return _get_case_or_404(session, case_id)


@router.get("/{case_id}/checklist", response_model=ChecklistResponse)
def get_checklist(
    case_id: UUID,
    session: Session = Depends(get_session),
    pack: RulePack = Depends(get_rule_pack),
) -> ChecklistResponse:
    case = _get_case_or_404(session, case_id)
    uploaded = {doc.slot: doc for doc in session.query(Document).filter_by(case_id=case.id)}

    slots: list[ChecklistSlot] = []
    missing: list[str] = []
    for required_slot in pack.required_slots:
        doc = uploaded.get(required_slot.slot)
        slots.append(
            ChecklistSlot(
                slot=required_slot.slot,
                doc_type=required_slot.doc_type,
                required=required_slot.required,
                needs_verification=required_slot.needs_verification,
                uploaded=doc is not None,
                document_id=doc.id if doc else None,
            )
        )
        if required_slot.required and doc is None:
            missing.append(required_slot.slot)

    return ChecklistResponse(case_id=case.id, slots=slots, missing_required_slots=missing)


@router.post(
    "/{case_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    case_id: UUID,
    slot: str,
    file: UploadFile,
    session: Session = Depends(get_session),
    pack: RulePack = Depends(get_rule_pack),
    key_manager: KeyManager = Depends(get_key_manager),
    blob_store: BlobStore = Depends(get_blob_store),
) -> Document:
    case = _get_case_or_404(session, case_id)

    known_slots = {required_slot.slot for required_slot in pack.required_slots}
    if slot not in known_slots:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{slot!r} is not a checklist slot")

    content = await file.read()

    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file exceeds the {settings.max_upload_size_bytes}-byte limit",
        )

    if _sniff_content_type(content) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "file is not a recognized PDF/PNG/JPG"
        )

    digest = service.sha256_hex(content)
    duplicate = session.query(Document).filter_by(case_id=case.id, sha256=digest).first()
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "identical content already uploaded for this case"
        )

    document = service.store_document(
        session,
        case=case,
        key_manager=key_manager,
        blob_store=blob_store,
        slot=slot,
        content=content,
        actor="provider",
    )
    session.commit()
    session.refresh(document)
    return document

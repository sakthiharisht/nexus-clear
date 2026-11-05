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

import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.auth import require_provider_token
from app.api.deps import (
    get_blob_store,
    get_extractor,
    get_fallback_backend,
    get_investigator,
    get_key_manager,
    get_phraser,
    get_primary_backend,
    get_rule_pack,
    get_session,
)
from app.api.schemas import (
    AttestRequest,
    AttestResponse,
    CaseCreatedResponse,
    CaseResponse,
    ChecklistResponse,
    ChecklistSlot,
    CreateCaseRequest,
    DocumentResponse,
)
from app.backends.base import DecisionBackend
from app.backends.extract_cache import CachedExtractor
from app.core.config import settings
from app.core.finding_store import load_case_findings
from app.core.orm import AuditLog, Case, Document, Extraction, ReviewItem
from app.escalate.engine import EscalationThresholds
from app.orchestrator.run import RunResult, run_case
from app.packet.builder import CaqhStylePacket, build_packet
from app.packet.gate import open_blocker_finding_ids, staleness_reason, unresolved_review_ids
from app.reconcile.cache import CachedInvestigator
from app.report.cache import CachedPhraser
from app.report.gap_report import GapReport, build_gap_report
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

_UPLOAD_CHUNK_SIZE = 64 * 1024


def _sniff_content_type(content: bytes) -> str | None:
    for mime, magic in _MAGIC_BYTES.items():
        if content.startswith(magic):
            return mime
    return None


def _oversize_error(max_bytes: int) -> HTTPException:
    return HTTPException(
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file exceeds the {max_bytes}-byte limit"
    )


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Reads `file` in fixed-size chunks, raising 413 the moment the
    running total exceeds `max_bytes` - a client claiming (or just
    sending) far more than the limit is never buffered past one chunk
    over it, unlike a single `await file.read()` which buffers the
    entire body in memory before any size check can run."""
    content = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise _oversize_error(max_bytes)
    return bytes(content)


def _get_case_or_404(session: Session, case_id: UUID) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"case {case_id} not found")
    return case


@router.post("", response_model=CaseCreatedResponse, status_code=status.HTTP_201_CREATED)
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
    # Generated here, not left to the ORM's flush-time default, because
    # create_wrapped_case_key needs the real id for its AAD before the
    # row exists.
    case_id = uuid4()
    case = Case(
        id=case_id,
        payer=body.payer,
        provider_type=body.provider_type,
        provider_profile=body.provider_profile.model_dump(mode="json"),
        target_date=target_date,
        wrapped_data_key=service.create_wrapped_case_key(key_manager, case_id=case_id),
        # Pre-M9 fix #4: this response is the only time it's ever shown.
        provider_token=secrets.token_urlsafe(24),
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
    # MaxContentLengthMiddleware (app/main.py) already rejected a
    # too-large Content-Length before this handler - and before
    # Starlette's multipart parser read any of the body - for a client
    # that reports its size honestly. _read_bounded below is the
    # backstop for a body that understates or omits Content-Length.
    case = _get_case_or_404(session, case_id)

    known_slots = {required_slot.slot for required_slot in pack.required_slots}
    if slot not in known_slots:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{slot!r} is not a checklist slot")

    content = await _read_bounded(file, settings.max_upload_size_bytes)

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


@router.post("/{case_id}/run", response_model=RunResult)
def run(
    case_id: UUID,
    session: Session = Depends(get_session),
    pack: RulePack = Depends(get_rule_pack),
    key_manager: KeyManager = Depends(get_key_manager),
    blob_store: BlobStore = Depends(get_blob_store),
    primary_backend: DecisionBackend = Depends(get_primary_backend),
    fallback_backend: DecisionBackend | None = Depends(get_fallback_backend),
    extractor: CachedExtractor = Depends(get_extractor),
    investigator: CachedInvestigator = Depends(get_investigator),
) -> RunResult:
    case = _get_case_or_404(session, case_id)
    return run_case(
        session,
        case=case,
        pack=pack,
        key_manager=key_manager,
        blob_store=blob_store,
        primary_backend=primary_backend,
        fallback_backend=fallback_backend,
        extractor=extractor,
        investigator=investigator,
        tau_classify=settings.tau_classify,
        legible_threshold=settings.legible_threshold,
        escalation_thresholds=EscalationThresholds(
            low_confidence_threshold=settings.low_confidence_threshold,
            blocker_confidence_threshold=settings.blocker_confidence_threshold,
        ),
    )


@router.get("/{case_id}/report", response_model=GapReport)
def get_report(
    case_id: UUID,
    session: Session = Depends(get_session),
    pack: RulePack = Depends(get_rule_pack),
    phraser: CachedPhraser = Depends(get_phraser),
) -> GapReport:
    case = _get_case_or_404(session, case_id)
    findings = [finding for _, finding in load_case_findings(session, case.id)]
    rule_titles = {rule.id: rule.title for rule in pack.rules}
    return build_gap_report(findings, rule_titles=rule_titles, phraser=phraser)


def _case_extractions(session: Session, case_id: UUID) -> list[Extraction]:
    return (
        session.query(Extraction)
        .join(Document, Extraction.document_id == Document.id)
        .filter(Document.case_id == case_id)
        .all()
    )


@router.post("/{case_id}/attest", response_model=AttestResponse)
def attest(
    case_id: UUID,
    body: AttestRequest,
    session: Session = Depends(get_session),
    case: Case = Depends(require_provider_token),
) -> AttestResponse:
    if case.attested_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "case is already attested")

    documents = session.query(Document).filter_by(case_id=case.id).all()
    review_items = session.query(ReviewItem).filter_by(case_id=case.id).all()
    stale_reason = staleness_reason(
        last_run_at=case.last_run_at, documents=documents, review_items=review_items
    )
    if stale_reason is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"cannot attest: {stale_reason} - run the case again first"
        )

    findings = [finding for _, finding in load_case_findings(session, case.id)]
    open_blockers = open_blocker_finding_ids(findings)
    if open_blockers:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cannot attest: open blocker findings exist: {', '.join(open_blockers)}",
        )

    unresolved = unresolved_review_ids(review_items)
    if unresolved:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cannot attest: unresolved review items exist: {', '.join(unresolved)}",
        )

    packet = build_packet(
        case.id,
        provider_profile=case.provider_profile,
        extractions=_case_extractions(session, case.id),
    )
    packet_json = json.dumps(packet.model_dump(mode="json"), sort_keys=True)
    packet_hash = hashlib.sha256(packet_json.encode()).hexdigest()

    now = datetime.now(UTC)
    case.attested_by = body.attested_by
    case.attested_at = now
    case.attested_packet = packet.model_dump(mode="json")
    case.attested_packet_hash = packet_hash
    case.state = "attested"

    session.add(
        AuditLog(
            actor=body.attested_by,
            action="case_attested",
            case_id=case.id,
            detail={"typed_name": body.typed_name, "packet_hash": packet_hash},
        )
    )
    session.commit()

    return AttestResponse(
        case_id=case.id, attested_by=body.attested_by, attested_at=now, packet_hash=packet_hash
    )


@router.get("/{case_id}/packet", response_model=CaqhStylePacket)
def get_packet(case_id: UUID, session: Session = Depends(get_session)) -> CaqhStylePacket:
    case = _get_case_or_404(session, case_id)
    if case.attested_packet is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "no packet yet - the case has not been attested"
        )
    return CaqhStylePacket.model_validate(case.attested_packet)

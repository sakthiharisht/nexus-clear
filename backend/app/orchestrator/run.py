"""Case run orchestrator (SPEC.md section 7.10, API surface section 8's
`POST /cases/{id}/run`): drives one case's uploaded documents through
Classify -> Extract -> Reconcile -> Validate -> Escalate and persists
the result (Extraction + FindingRecord + ReviewItem rows), the one
place a live Case actually gets real Findings. Extraction rows store
the verified field dict (app/core/extract_verify.py) per document -
the only place Extract's per-field output survives past this request,
and what app/packet/builder.py reads back out to prefill a packet from
verified fields only (CLAUDE.md invariant 2 - nothing here is parsed
back out of a Finding's free-text evidence quote, which was never
meant to be machine-read).

Not the full state-machine orchestrator SPEC 7.10 describes (idempotent
per-stage re-run, a durable runner per case) - this is a single
synchronous pass, re-run safe only in the sense that re-running it adds
new FindingRecord/ReviewItem rows rather than mutating old ones. The
durable, resumable version is a stretch goal; a demo-scale case
finishes this pass in well under the request timeout.

Backends (primary/fallback DecisionBackend, ExtractionBackend,
InvestigatorLike) are injected, not constructed here - app.backends.factory
wires them from settings at the API layer, so this module stays
testable with fakes the same way app/eval's runners are.

Assumption flagged, not silently guessed: `Case.provider_profile`
(an opaque dict since M4 - CreateCaseRequest never typed its internal
shape) is read here as a flat dict whose keys line up with
ProfileFacts/SupervisionFacts field names directly (e.g. "legal_name",
"npi", "supervisor_count") - both models ignore unrecognized keys, so
one dict feeds both. If a real intake form's shape differs, this is
the one place to adjust, not a cross-cutting change.
"""

from __future__ import annotations

import io
import logging
from base64 import b64encode
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import pypdf
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.backends.base import DecisionBackend
from app.backends.extract_cache import ExtractionBackend
from app.backends.extract_types import (
    DOC_TYPE_TO_EXTRACT_KIND,
    CoiExtraction,
    CvExtraction,
    ExtractInput,
    LicenseExtraction,
)
from app.backends.policy import ClassifyDecision, decide
from app.backends.types import DOC_TYPES, ClassificationResult, ClassifyInput
from app.core.contracts import Finding
from app.core.extract_verify import (
    verify_coi_extraction,
    verify_cv_extraction,
    verify_license_extraction,
)
from app.core.injection import contains_injection_text
from app.core.orm import AuditLog, Case, Document, Extraction, FindingRecord, ReviewItem
from app.escalate.engine import EscalationThresholds, escalate
from app.pipeline.extract_to_case_facts import (
    apply_coi_extraction,
    apply_cv_extraction,
    apply_license_extraction,
)
from app.reconcile.engine import reconcile
from app.reconcile.investigator import InvestigatorLike
from app.rules.context import CaseFacts, DocumentFact, ProfileFacts, SupervisionFacts
from app.rules.engine import evaluate_rule_pack
from app.rules.schema import RulePack
from app.vault import service as vault_service
from app.vault.blob_store import BlobStore
from app.vault.key_manager import KeyManager

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class RunResult(BaseModel):
    case_id: UUID
    findings: list[Finding]
    escalated_finding_ids: list[str]
    extraction_notes: list[str]


def _classify_bits(
    content: bytes,
) -> tuple[str, str | None, Literal["image/png", "image/jpeg"] | None]:
    """(page1_text, image_b64, image_media_type) for one document's raw
    bytes. Unlike app/eval/classify_run.py's deliberate "no image"
    scope (cross-platform cache-key reproducibility isn't a concern
    for a real upload), a document with no text layer gets its raw
    bytes attached so a vision-capable backend has something to judge
    legibility/doc_type from, instead of nothing."""
    if content.startswith(_PDF_MAGIC):
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
        except Exception:
            return "", None, None
        if not reader.pages:
            return "", None, None
        return reader.pages[0].extract_text() or "", None, None
    if content.startswith(_PNG_MAGIC):
        return "", b64encode(content).decode(), "image/png"
    if content.startswith(_JPEG_MAGIC):
        return "", b64encode(content).decode(), "image/jpeg"
    return "", None, None


def _full_text(content: bytes) -> str:
    """Every page's text, joined - Extract's input (app/eval/extract_run.py's
    `full_text` does the same over a file path; this is the bytes
    equivalent for a document decrypted straight from the vault, never
    written to disk). Deliberately text-only, same scope boundary as
    extract_run.py: vision-based live extraction is not built here."""
    if not content.startswith(_PDF_MAGIC):
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
    except Exception:
        return ""
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def run_case(
    session: Session,
    *,
    case: Case,
    pack: RulePack,
    key_manager: KeyManager,
    blob_store: BlobStore,
    primary_backend: DecisionBackend,
    fallback_backend: DecisionBackend | None,
    extractor: ExtractionBackend,
    investigator: InvestigatorLike,
    tau_classify: float,
    legible_threshold: float,
    escalation_thresholds: EscalationThresholds,
) -> RunResult:
    documents = session.query(Document).filter_by(case_id=case.id).all()
    required_by_slot = {slot.slot: slot for slot in pack.required_slots}

    facts = CaseFacts(
        target_date=case.target_date,
        profile=ProfileFacts.model_validate(case.provider_profile),
        supervision=SupervisionFacts.model_validate(case.provider_profile),
    )

    document_facts: list[DocumentFact] = []
    extraction_notes: list[str] = []
    unverified_namespaces: set[str] = set()

    for document in documents:
        required_slot = required_by_slot.get(document.slot)
        if required_slot is None:
            # Defensive only - the real upload endpoint already rejects
            # a slot the current rule pack doesn't define.
            continue

        plaintext = vault_service.read_document(
            session, case=case, document=document, key_manager=key_manager,
            blob_store=blob_store, actor="orchestrator",
        )
        page1_text, image_b64, image_media_type = _classify_bits(plaintext)

        classify_input = ClassifyInput(
            slot=document.slot,
            filename=f"{document.sha256}/{document.slot}",
            allowed_doc_types=list(DOC_TYPES),
            page1_text=page1_text,
            page1_image_b64=image_b64,
            page1_image_media_type=image_media_type,
        )
        try:
            classify_decision = decide(
                classify_input, primary=primary_backend, fallback=fallback_backend,
                tau_classify=tau_classify, legible_threshold=legible_threshold,
            )
        except ValueError as exc:
            logger.warning(
                "classify failed case_id=%s slot=%s backend=%s: %s",
                case.id, document.slot, primary_backend.name, exc,
            )
            classify_decision = ClassifyDecision(
                result=ClassificationResult(
                    doc_type="other", probabilities={}, legible=0.0, slot_match=False,
                    decided_by=primary_backend.name,  # type: ignore[arg-type]
                ),
                accepted=False, escalated=True, reason=f"{primary_backend.name} raised: {exc}",
            )

        result = classify_decision.result
        document.classification = result.model_dump(mode="json")

        full_text = _full_text(plaintext)
        document_facts.append(
            DocumentFact(
                doc_id=str(document.id),
                slot=document.slot,
                expected_doc_type=required_slot.doc_type,
                uploaded_doc_type=result.doc_type,
                legible_score=result.legible,
                contains_injection_text=contains_injection_text(full_text) if full_text else False,
                readable=bool(full_text) or image_b64 is not None,
            )
        )

        if not classify_decision.accepted:
            extraction_notes.append(
                f"{document.slot}: classification escalated "
                f"({classify_decision.reason}) - not extracted"
            )
            continue

        extract_kind = DOC_TYPE_TO_EXTRACT_KIND.get(result.doc_type)
        expected_kind = DOC_TYPE_TO_EXTRACT_KIND.get(required_slot.doc_type)
        if extract_kind is None or extract_kind != expected_kind:
            extraction_notes.append(
                f"{document.slot}: classified doc type doesn't match this schema - not extracted"
            )
            continue
        if extract_kind not in ("license", "coi", "cv"):
            # education/w9: extraction schemas exist and are citation-
            # verified (app/core/extract_verify.py) but CaseFacts has no
            # namespace to project them into - no rule reads either one
            # (see app/eval/extract_run.py's own docstring) - so there's
            # nothing to gain from spending a live call here.
            continue
        if not full_text and image_b64 is None:
            extraction_notes.append(
                f"{document.slot}: no extractable text layer or image - left unknown"
            )
            continue

        # None (not "") when there's no text layer at all - a document
        # with a *real* empty text layer should still fail quote
        # verification against "" (app/core/citations.py's verify_field
        # docstring), but an image has no text layer to check against in
        # the first place, which is a different, unverifiable-by-code
        # situation (quote_verified stays False, never promoted to True
        # or demoted to "unknown" just because there's nothing to compare
        # against).
        verify_against_text = full_text if image_b64 is None else None

        extract_input_doc_id = f"doc-{document.slot}"
        try:
            extraction_result = extractor.extract(
                ExtractInput(
                    doc_id=extract_input_doc_id, kind=extract_kind,
                    filename=f"{document.sha256}/{document.slot}", document_text=full_text,
                    # A document with no text layer still has a chance to
                    # be read via vision (e.g. a scanned/rotated license) -
                    # cached on the image's own sha256, not case-id/upload-
                    # order (app/backends/extract_cache.py), so re-uploading
                    # the same bytes elsewhere still hits the same fixture.
                    image_b64=image_b64 if not full_text else None,
                    image_media_type=image_media_type if not full_text else None,
                )
            )
        except ValueError as exc:
            extraction_notes.append(f"{document.slot}: extraction failed ({exc}) - left unknown")
            continue

        if extract_kind == "license":
            assert isinstance(extraction_result.fields, LicenseExtraction)
            verified_dict = verify_license_extraction(extraction_result.fields, verify_against_text)
            verified_fields = list(verified_dict.values())
            verified_payload: dict[str, object] = {
                name: field.model_dump(mode="json") for name, field in verified_dict.items()
            }
            facts = apply_license_extraction(
                facts, extract_input_doc_id, extraction_result.fields, verify_against_text
            )
            namespace = "license"
        elif extract_kind == "coi":
            assert isinstance(extraction_result.fields, CoiExtraction)
            verified_dict = verify_coi_extraction(extraction_result.fields, verify_against_text)
            verified_fields = list(verified_dict.values())
            verified_payload = {
                name: field.model_dump(mode="json") for name, field in verified_dict.items()
            }
            facts = apply_coi_extraction(
                facts, extract_input_doc_id, extraction_result.fields, verify_against_text
            )
            namespace = "coi"
        elif extract_kind == "cv":
            assert isinstance(extraction_result.fields, CvExtraction)
            verified_cv = verify_cv_extraction(extraction_result.fields, verify_against_text)
            facts = apply_cv_extraction(
                facts, extract_input_doc_id, extraction_result.fields, verify_against_text
            )
            namespace = "cv"
            verified_fields = [verified_cv["name"], *verified_cv["education"]]
            for position in verified_cv["positions"]:
                verified_fields.extend(
                    [position["title"], position["employer"], position["start"], position["end"]]
                )
            verified_payload = {
                "name": verified_cv["name"].model_dump(mode="json"),
                "education": [f.model_dump(mode="json") for f in verified_cv["education"]],
                "positions": [
                    {
                        "title": position["title"].model_dump(mode="json"),
                        "employer": position["employer"].model_dump(mode="json"),
                        "start": position["start"].model_dump(mode="json"),
                        "end": position["end"].model_dump(mode="json"),
                    }
                    for position in verified_cv["positions"]
                ],
            }
        else:  # pragma: no cover - unreachable: the education/w9 guard above already skipped these
            continue

        if any(field.status == "known" and not field.quote_verified for field in verified_fields):
            unverified_namespaces.add(namespace)

        session.add(
            Extraction(
                document_id=document.id,
                schema_version=extract_kind,
                fields=verified_payload,
                model=extractor.name,
            )
        )

    facts = facts.model_copy(update={"documents": document_facts})
    facts = reconcile(pack, facts, investigator=investigator)
    findings = evaluate_rule_pack(pack, facts, case.target_date)

    # Carry forward prior human decisions (pre-M9 fix #2): without
    # this, a rule a reviewer already resolved would re-escalate on
    # every subsequent run with identical confidence, making it
    # impossible to ever clear the queue for a data-level issue
    # (confidence doesn't change just because a human looked at it).
    # A rule_id a human has already resolved for this case is never
    # asked about again; its decision is reapplied directly instead.
    prior_resolutions_by_rule: dict[str, ReviewItem] = {}
    for item in session.query(ReviewItem).filter_by(case_id=case.id, status="resolved").all():
        prior_record = session.get(FindingRecord, item.finding_id)
        if prior_record is None:
            continue
        prior_rule_id = prior_record.finding.get("rule_id")
        if not isinstance(prior_rule_id, str):
            continue
        existing = prior_resolutions_by_rule.get(prior_rule_id)
        if existing is None or (
            item.resolved_at is not None
            and existing.resolved_at is not None
            and item.resolved_at > existing.resolved_at
        ):
            prior_resolutions_by_rule[prior_rule_id] = item

    finding_id_to_record_id: dict[str, UUID] = {}
    already_reviewed_rule_ids: set[str] = set()
    for finding in findings:
        prior = prior_resolutions_by_rule.get(finding.rule_id)
        finding_payload = finding.model_dump(mode="json")
        if prior is not None:
            already_reviewed_rule_ids.add(finding.rule_id)
            resolution = prior.reviewer_resolution or {}
            finding_payload["decided_by"] = "human"
            if resolution.get("decision") == "override" and resolution.get("override_status"):
                finding_payload["status"] = resolution["override_status"]

        record = FindingRecord(
            case_id=case.id, rule_pack_version=pack.version, finding=finding_payload
        )
        session.add(record)
        session.flush()
        finding_id_to_record_id[finding.finding_id] = record.id

    decisions = escalate(
        findings,
        rules_by_id={rule.id: rule for rule in pack.rules},
        unverified_namespaces=unverified_namespaces,
        thresholds=escalation_thresholds,
    )
    escalated_finding_ids: list[str] = []
    for decision in decisions:
        if not decision.escalated or decision.rule_id in already_reviewed_rule_ids:
            continue
        escalated_finding_ids.append(decision.finding_id)
        session.add(
            ReviewItem(
                case_id=case.id,
                finding_id=finding_id_to_record_id[decision.finding_id],
                status="pending",
            )
        )

    case.state = "reconciled"
    case.last_run_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor="orchestrator",
            action="case_run",
            case_id=case.id,
            detail={
                "finding_count": len(findings),
                "escalated_count": len(escalated_finding_ids),
                "extraction_note_count": len(extraction_notes),
            },
        )
    )
    session.commit()

    return RunResult(
        case_id=case.id,
        findings=findings,
        escalated_finding_ids=escalated_finding_ids,
        extraction_notes=extraction_notes,
    )

"""Reviewer queue API (SPEC.md section 7.9 / section 8): list escalated
items, view the evidence behind one, and resolve it. A resolution
updates the underlying Finding's `decided_by` to "human" (CLAUDE.md
invariant 1 still holds - no model output set the status; a named
human reviewer did, and that's recorded, not silently overwritten as
if code had decided it) and is itself an audit row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import (
    ResolveReviewRequest,
    ReviewItemDetailResponse,
    ReviewItemResponse,
)
from app.core.contracts import Finding
from app.core.orm import AuditLog, FindingRecord, ReviewItem

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _get_review_item_or_404(session: Session, review_id: UUID) -> ReviewItem:
    item = session.get(ReviewItem, review_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"review item {review_id} not found")
    return item


@router.get("", response_model=list[ReviewItemResponse])
def list_reviews(
    case_id: UUID | None = None,
    review_status: str | None = None,
    session: Session = Depends(get_session),
) -> list[ReviewItem]:
    query = session.query(ReviewItem)
    if case_id is not None:
        query = query.filter_by(case_id=case_id)
    if review_status is not None:
        query = query.filter_by(status=review_status)
    return query.all()


@router.get("/{review_id}", response_model=ReviewItemDetailResponse)
def get_review(review_id: UUID, session: Session = Depends(get_session)) -> dict[str, object]:
    item = _get_review_item_or_404(session, review_id)
    record = session.get(FindingRecord, item.finding_id)
    if record is None:  # pragma: no cover - defensive: FK guarantees this exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "underlying finding not found")
    return {
        "id": item.id,
        "case_id": item.case_id,
        "finding_id": item.finding_id,
        "status": item.status,
        "reviewer_resolution": item.reviewer_resolution,
        "created_at": item.created_at,
        "resolved_at": item.resolved_at,
        "finding": Finding.model_validate(record.finding),
    }


@router.post("/{review_id}/resolve", response_model=ReviewItemResponse)
def resolve_review(
    review_id: UUID, body: ResolveReviewRequest, session: Session = Depends(get_session)
) -> ReviewItem:
    item = _get_review_item_or_404(session, review_id)
    if item.status == "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "review item is already resolved")
    if body.decision == "override" and body.override_status is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "override_status is required when decision is 'override'"
        )

    record = session.get(FindingRecord, item.finding_id)
    if record is None:  # pragma: no cover - defensive: FK guarantees this exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "underlying finding not found")

    finding = dict(record.finding)
    finding["decided_by"] = "human"
    if body.decision == "override":
        finding["status"] = body.override_status
    record.finding = finding

    now = datetime.now(UTC)
    item.status = "resolved"
    item.resolved_at = now
    item.reviewer_resolution = {
        "decision": body.decision,
        "note": body.note,
        "resolved_by": body.resolved_by,
        "override_status": body.override_status,
    }

    session.add(
        AuditLog(
            actor=body.resolved_by,
            action="review_resolved",
            case_id=item.case_id,
            object_ref=str(item.id),
            detail={"decision": body.decision, "finding_id": str(item.finding_id)},
        )
    )
    session.commit()
    session.refresh(item)
    return item

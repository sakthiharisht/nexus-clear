"""Human gate preconditions (SPEC.md section 7.9): "Open blockers or
unresolved review items block attestation." Pure checks over already-
loaded data - the API layer (app/api/cases.py) does the loading.
"""

from __future__ import annotations

from datetime import datetime

from app.core.contracts import Finding
from app.core.orm import Document, ReviewItem


def open_blocker_finding_ids(findings: list[Finding]) -> list[str]:
    return [
        finding.finding_id
        for finding in findings
        if finding.severity == "blocker" and finding.status in ("fail", "unknown")
    ]


def unresolved_review_ids(review_items: list[ReviewItem]) -> list[str]:
    return [str(item.id) for item in review_items if item.status != "resolved"]


def staleness_reason(
    *, last_run_at: datetime | None, documents: list[Document], review_items: list[ReviewItem]
) -> str | None:
    """None when the case's last run is current with everything else
    that happened since - otherwise the reason attestation must wait
    for a fresh POST /cases/{id}/run (pre-M9 fix #2: the packet/
    findings being attested must reflect the latest uploads and
    review decisions, not a run that predates one of them)."""
    if last_run_at is None:
        return "case has never been run"
    stale_upload = next((d for d in documents if d.uploaded_at > last_run_at), None)
    if stale_upload is not None:
        return f"document {stale_upload.id} was uploaded after the last run"
    stale_review = next(
        (r for r in review_items if r.resolved_at is not None and r.resolved_at > last_run_at),
        None,
    )
    if stale_review is not None:
        return f"review item {stale_review.id} was resolved after the last run"
    return None

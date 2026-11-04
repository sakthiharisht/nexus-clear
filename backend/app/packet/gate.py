"""Human gate preconditions (SPEC.md section 7.9): "Open blockers or
unresolved review items block attestation." Pure checks over already-
loaded data - the API layer (app/api/cases.py) does the loading.
"""

from __future__ import annotations

from app.core.contracts import Finding
from app.core.orm import ReviewItem


def open_blocker_finding_ids(findings: list[Finding]) -> list[str]:
    return [
        finding.finding_id
        for finding in findings
        if finding.severity == "blocker" and finding.status in ("fail", "unknown")
    ]


def unresolved_review_ids(review_items: list[ReviewItem]) -> list[str]:
    return [str(item.id) for item in review_items if item.status != "resolved"]

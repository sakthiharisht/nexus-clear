"""Reads persisted FindingRecord rows (app/core/orm.py) back into the
Finding contract (app/core/contracts.py) - the read side of what
app/orchestrator/run.py writes. Shared by every endpoint that needs a
case's findings (report, reviewer queue, packet, attest), so there's
one place that does this translation.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.contracts import Finding
from app.core.orm import FindingRecord


def load_case_findings(session: Session, case_id: UUID) -> list[tuple[FindingRecord, Finding]]:
    """A case can be /run more than once (e.g. the stale-attest guard
    forces a re-run after a reviewer resolution). Each run persists a
    fresh FindingRecord per rule rather than overwriting the last run's
    - without the dedup below, every finding would double (triple,
    ...) per re-run. finding_id is stable across runs of the *same*
    case (it's the rule id, optionally suffixed with the document's
    row id - documents aren't re-created between runs), so "latest
    created_at wins per finding_id" always resolves to this case's
    current state.
    """
    records = (
        session.query(FindingRecord)
        .filter_by(case_id=case_id)
        .order_by(FindingRecord.created_at)
        .all()
    )
    latest_by_finding_id: dict[str, FindingRecord] = {}
    for record in records:
        finding_id = record.finding.get("finding_id")
        if isinstance(finding_id, str):
            latest_by_finding_id[finding_id] = record
    return [
        (record, Finding.model_validate(record.finding))
        for record in latest_by_finding_id.values()
    ]

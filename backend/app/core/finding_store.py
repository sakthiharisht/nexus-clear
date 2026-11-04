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
    records = session.query(FindingRecord).filter_by(case_id=case_id).all()
    return [(record, Finding.model_validate(record.finding)) for record in records]

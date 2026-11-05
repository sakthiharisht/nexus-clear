"""Audit log API (SPEC.md section 8: `GET /audit?case_id=`). Read-only;
app/core/orm.py's AuditLog is append-only at the DB level (a trigger
blocks UPDATE/DELETE even for this process's own connection).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import AuditLogEntryResponse
from app.core.orm import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogEntryResponse])
def list_audit_log(
    case_id: UUID | None = None, session: Session = Depends(get_session)
) -> list[AuditLog]:
    query = session.query(AuditLog)
    if case_id is not None:
        query = query.filter_by(case_id=case_id)
    return query.order_by(AuditLog.ts.desc()).all()

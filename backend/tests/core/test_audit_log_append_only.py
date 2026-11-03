"""audit_log must be append-only at the DB level, not just by
application convention (CLAUDE.md invariant 4; app/core/orm.py's
AuditLog docstring). Enforced by a trigger added in
alembic/versions/f99bfcd5627b_audit_log_append_only.py - a trigger, not
a REVOKE, because this project's DB role is a superuser that privilege
checks don't apply to; see that migration's docstring.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.orm import AuditLog


def _insert_probe_row(db_session: Session) -> None:
    db_session.add(AuditLog(actor="tester", action="probe"))
    db_session.flush()


def test_update_on_audit_log_is_rejected(db_session: Session) -> None:
    _insert_probe_row(db_session)

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(text("UPDATE audit_log SET actor = 'hacked' WHERE actor = 'tester'"))
    db_session.rollback()


def test_delete_on_audit_log_is_rejected(db_session: Session) -> None:
    _insert_probe_row(db_session)

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(text("DELETE FROM audit_log WHERE actor = 'tester'"))
    db_session.rollback()


def test_insert_on_audit_log_still_works(db_session: Session) -> None:
    _insert_probe_row(db_session)
    rows = db_session.query(AuditLog).filter_by(actor="tester").all()
    assert len(rows) == 1

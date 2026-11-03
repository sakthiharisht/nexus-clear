"""audit log append only

CLAUDE.md invariant 4 / app/core/orm.py's AuditLog docstring already say
"application code must never UPDATE or DELETE a row here" - this makes
that a DB-level guarantee instead of only an application convention.

A trigger, not a REVOKE, because this project's DB role (postgres, per
docker-compose.yml) is a superuser: GRANT/REVOKE privilege checks don't
apply to superusers at all, so revoking UPDATE/DELETE would enforce
nothing against the app's own connection. Triggers have no such bypass -
they fire for every role, superuser included - so a BEFORE UPDATE/DELETE
trigger that raises is the only one of the two that actually blocks this
project's own connection, not just a hypothetical lower-privileged one.

Revision ID: f99bfcd5627b
Revises: 196246052e48
Create Date: 2026-11-04 09:36:06.898260

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f99bfcd5627b'
down_revision: Union[str, Sequence[str], None] = '196246052e48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE FUNCTION audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update
        BEFORE UPDATE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_delete
        BEFORE DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")

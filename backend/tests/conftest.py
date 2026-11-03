"""Shared pytest fixtures. `db_session` is a real Postgres-backed
SQLAlchemy session, isolated per test via a transaction that's always
rolled back — CLAUDE.md's "do not mock the rules engine in integration
tests" extends here too: vault/API tests exercise the real ORM against a
real database, not a mock.

Requires a reachable Postgres at DATABASE_URL (app.core.config.settings),
already migrated to head: `docker compose up -d postgres` + `uv run
alembic upgrade head` locally; CI's postgres service container is already
configured and migrated before pytest runs (.github/workflows/ci.yml).

Route handlers call `session.commit()` (app/api/cases.py), which would
normally end the outer test transaction and break isolation — `Session(
join_transaction_mode="create_savepoint")` is SQLAlchemy 2.0's current
recommended fix: COMMIT closes a SAVEPOINT instead of the real
transaction, so the outer rollback in this fixture's teardown still
undoes everything. Verified against the current SQLAlchemy 2.0 docs
(docs.sqlalchemy.org/en/20/orm/session_transaction.html, "Joining a
Session into an External Transaction") before relying on it — this
replaced the older event-listener-based recipe.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import settings


@pytest.fixture(scope="session")
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()

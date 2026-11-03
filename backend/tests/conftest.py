"""Shared pytest fixtures. `db_session` is a real Postgres-backed
SQLAlchemy session, isolated per test via a transaction that's always
rolled back — CLAUDE.md's "do not mock the rules engine in integration
tests" extends here too: vault/API tests exercise the real ORM against a
real database, not a mock.

Requires a reachable Postgres at DATABASE_URL (app.core.config.settings),
already migrated to head: `docker compose up -d postgres` + `uv run
alembic upgrade head` locally; CI's postgres service container is already
configured and migrated before pytest runs (.github/workflows/ci.yml).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

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
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()

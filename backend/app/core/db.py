"""SQLAlchemy 2.0 engine and session plumbing.

Sync engine + sync sessions (psycopg3). The MVP's traffic is low (one
provider working one case at a time); a sync engine run through FastAPI's
threadpool keeps the stack simple without async-session caveats. Revisit if
load ever justifies it.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models (app/core/orm.py)."""


engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, always closed after the request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

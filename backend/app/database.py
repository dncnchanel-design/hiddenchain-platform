from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .migrations import apply_migrations, migration_status


@event.listens_for(Engine, "connect")
def _enable_sqlite_integrity(dbapi_connection, _connection_record) -> None:
    """Enforce declared foreign keys on every SQLite connection.

    SQLite leaves foreign-key enforcement disabled unless each connection opts
    in.  Registering the listener on ``Engine`` also covers isolated engines
    used by migration tests and administrative scripts.
    """

    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_runtime_schema() -> None:
    """Backward-compatible entry point for the versioned migration runner."""

    apply_migrations(engine)


def database_readiness() -> dict[str, object]:
    return migration_status(engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

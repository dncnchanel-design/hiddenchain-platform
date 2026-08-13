from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_runtime_schema() -> None:
    """Apply the tiny additive migrations used by the demo deployment.

    The project intentionally keeps deployment lightweight, so a full migration
    framework would be disproportionate here.  These changes are additive and
    safe for an existing SQLite or PostgreSQL demo database.
    """

    additions = {
        "data_uploads": {
            "ingress_json": "JSON NOT NULL DEFAULT '{}'",
        },
        "settlement_tasks": {
            "verification_profile_json": "JSON NOT NULL DEFAULT '{}'",
        },
        "privacy_compute_jobs": {
            "privacy_guarantees_json": "JSON NOT NULL DEFAULT '{}'",
        },
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table_name, columns in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_definition in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN "
                            f"{column_name} {column_definition}"
                        )
                    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

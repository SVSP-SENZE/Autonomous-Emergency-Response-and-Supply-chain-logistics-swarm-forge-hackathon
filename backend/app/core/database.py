"""Database engine, session factory and base declarative class."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def _is_sqlite(url: str) -> bool:
    return url.strip().lower().startswith("sqlite")


def _sqlite_connect_args() -> dict[str, object]:
    # FastAPI test clients and uvicorn may touch the session from different
    # threads; SQLite requires `check_same_thread=False` for that.
    return {"check_same_thread": False}


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """SQLite does not enforce foreign keys unless explicitly enabled."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        # Brief lock contention (e.g. an agent tool write during another
        # request's read) should wait instead of failing instantly.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


engine = create_engine(
    settings.database_url,
    connect_args=_sqlite_connect_args() if _is_sqlite(settings.database_url) else {},
)
if _is_sqlite(settings.database_url):
    _enable_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables.

    Importing `app.models` ensures every model is registered on
    `Base.metadata` before the tables are created.
    """
    from app import models  # noqa: F401  (import for side effects)

    Base.metadata.create_all(bind=engine)

"""Shared pytest fixtures.

Every test runs against an isolated temporary SQLite database created in
`tmp_path`, so the development database is never touched. Startup auto-init /
auto-seed are disabled via environment variables BEFORE the app is imported.
"""

from __future__ import annotations

import os
from pathlib import Path

# Must be set before `app.main` / `app.core.config` are imported.
os.environ["AUTO_INIT_DB"] = "false"
os.environ["AUTO_SEED"] = "false"
os.environ.setdefault("DATABASE_URL", "sqlite:///./pytest_placeholder.db")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Tests run offline against the seeded DB road graph; the real OSM network
# (default for operational routing) is never downloaded in tests.
os.environ["ROUTING_NETWORK"] = "simulated"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.seed_service import seed_demo  # noqa: E402


def _enable_sqlite_fk(dbapi_connection: object, record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def db_engine(tmp_path: Path):
    """Isolated file-backed SQLite database for one test."""
    db_path = tmp_path / "reliefmesh_test.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", _enable_sqlite_fk)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db(session_factory):
    """A raw (unseeded) database session."""
    with session_factory() as session:
        yield session


@pytest.fixture()
def seeded_db(session_factory):
    """A database session with the demo scenario seeded."""
    with session_factory() as session:
        seed_demo(session)
        yield session


@pytest.fixture()
def client(session_factory):
    """FastAPI test client wired to the isolated test database (seeded)."""
    seed_session = session_factory()
    try:
        seed_demo(seed_session)
    finally:
        seed_session.close()

    def _override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()

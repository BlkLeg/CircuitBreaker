import os

# Force NATS to fail fast in tests (unreachable port) so lifespan doesn't hang
os.environ.setdefault("NATS_URL", "nats://127.0.0.1:19999")

# v0.2.0: app.db.session requires CB_DB_URL to be postgresql:// at import time.
# Schema uses JSONB (PostgreSQL-only), so tests need a real Postgres or are skipped.
os.environ["CB_DB_URL"] = (
    os.environ.get("CB_TEST_DB_URL")
    or os.environ.get("CB_DB_URL")
    or "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"
)

# Test DB URL for fixtures. Schema uses JSONB (PostgreSQL-only), so default is Postgres.
_TEST_DB_URL_DEFAULT = "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"
TEST_DB_URL = os.environ.get("CB_TEST_DB_URL") or os.environ.get("CB_DB_URL") or _TEST_DB_URL_DEFAULT

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import (
    compat as _compat,  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi import
)
from app.core.rate_limit import limiter
from app.db.session import Base, get_db

limiter.enabled = False  # Disable rate-limiting during tests
from app.db import models  # noqa: F401 E402 — register models with metadata
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def db_engine():
    if TEST_DB_URL.startswith("sqlite"):
        engine = create_engine(
            TEST_DB_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        # Provide larger pool size for async tests running concurrently
        os.environ["DB_POOL_SIZE"] = "20"
        engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
        
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine):
    with db_engine.connect() as conn:
        if TEST_DB_URL.startswith("sqlite"):
            # Fallback for SQLite (unsupported, but keeping code paths alive)
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
        else:
            # Fast clear of all data between tests using Postgres native cascade
            tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
            if tables:
                conn.execute(text(f"TRUNCATE TABLE {tables} CASCADE;"))
        conn.commit()

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_engine, db, monkeypatch):
    # Mock NATS connect to avoid slow connection attempts in tests
    import app.core.nats_client as nats_mod

    async def _noop_connect():
        nats_mod.nats_client._connected = False
        nats_mod.nats_client._nc = None

    monkeypatch.setattr(nats_mod.nats_client, "connect", _noop_connect)

    test_session = sessionmaker(bind=db_engine)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    # Patch SessionLocal at its source so that write_log (which imports it locally
    # on each call) and the logging middleware (module-level import) both use the
    # test DB instead of the production SQLite file.
    import app.core.config as _config
    import app.db.session as _db_session
    import app.main as _main
    import app.middleware.logging_middleware as _log_mw

    orig_session_local = _db_session.SessionLocal
    orig_mw_session_local = _log_mw.SessionLocal
    orig_main_session_local = getattr(_main, "SessionLocal", None)
    orig_main_engine = getattr(_main, "engine", None)
    orig_db_session_engine = getattr(_db_session, "engine", None)
    orig_db_url = getattr(_config.settings, "database_url", None)

    _db_session.SessionLocal = test_session
    _log_mw.SessionLocal = test_session
    if orig_main_session_local is not None:
        _main.SessionLocal = test_session
    if orig_main_engine is not None:
        _main.engine = db_engine
    if orig_db_session_engine is not None:
        _db_session.engine = db_engine
    _config.settings.database_url = TEST_DB_URL

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    _db_session.SessionLocal = orig_session_local
    _log_mw.SessionLocal = orig_mw_session_local
    if orig_main_session_local is not None:
        _main.SessionLocal = orig_main_session_local
    if orig_main_engine is not None:
        _main.engine = orig_main_engine
    if orig_db_session_engine is not None:
        _db_session.engine = orig_db_session_engine
    if orig_db_url is not None:
        _config.settings.database_url = orig_db_url


@pytest.fixture
def auth_headers(client):
    """Bootstrap the app (enables auth), log in, and return Bearer auth headers.

    Only use this fixture in tests that explicitly test authenticated behaviour.
    Most tests run on a fresh DB where auth_enabled=False and do not need it.
    """
    client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "test@example.com",
            "password": "Secure1234!",
            "theme_preset": "one-dark",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "Secure1234!",
        },
    )
    token = login_resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}

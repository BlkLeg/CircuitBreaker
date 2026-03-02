import pytest
import sentry_sdk
from app.core import compat as _compat  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi/sentry_sdk import
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.core.rate_limit import limiter
limiter.enabled = False  # Disable rate-limiting during tests
from app.db import models  # noqa: F401 E402 — register models with metadata
from app.main import app  # noqa: E402

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session", autouse=True)
def disable_sentry():
    """Close the Sentry transport immediately so no events are queued or flushed
    during test runs, regardless of what DSN is set in backend/.env."""
    sentry_sdk.get_client().close(timeout=0)


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_engine, db):
    test_session = sessionmaker(bind=db_engine)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    # Patch SessionLocal at its source so that write_log (which imports it locally
    # on each call) and the logging middleware (module-level import) both use the
    # test DB instead of the production SQLite file.
    import app.db.session as _db_session
    import app.middleware.logging_middleware as _log_mw

    orig_session_local = _db_session.SessionLocal
    orig_mw_session_local = _log_mw.SessionLocal

    _db_session.SessionLocal = test_session
    _log_mw.SessionLocal = test_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    _db_session.SessionLocal = orig_session_local
    _log_mw.SessionLocal = orig_mw_session_local


@pytest.fixture
def auth_headers(client):
    """Bootstrap the app (enables auth), log in, and return Bearer auth headers.

    Only use this fixture in tests that explicitly test authenticated behaviour.
    Most tests run on a fresh DB where auth_enabled=False and do not need it.
    """
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "test@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
    })
    resp = client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "Secure1234!",
    })
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}

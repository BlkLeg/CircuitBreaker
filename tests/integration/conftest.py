import os

# Force NATS to fail fast in tests (unreachable port) so lifespan doesn't hang
os.environ.setdefault("NATS_URL", "nats://127.0.0.1:19999")

# No outbound release check from a test run. The suite runs with
# CB_ALLOW_DIRECT_EGRESS=true (the Makefile explains why), so without this every
# `client` fixture — several hundred of them — really dials api.github.com from
# lifespan startup and has that call cancelled by lifespan shutdown a moment
# later. Cancelling httpx while it is still connecting leaks the socket and its
# transport: the connection has not reached the pool yet, so `AsyncClient.aclose()`
# cannot close it, and the finalizer surfaces it as an unraisable ResourceWarning
# charged to whichever unrelated test the garbage collector happens to interrupt.
# That is what made test_discovery.py and test_oobe_smoke.py fail on unclosed
# sockets to 140.82.x.x:443 while pointing at nothing in their own code.
#
# Nothing is lost by disabling it: no test here asserts on the update verdict, and
# app.core.update_check has its own coverage in apps/backend/tests/core/test_update_*.py
# via its transport seam. Tests do not get to depend on GitHub being reachable, on
# its 60-requests-per-hour anonymous rate limit, or on connect timing.
os.environ.setdefault("CB_UPDATE_CHECK", "false")

# Use a writable temp dir so the app lifespan doesn't crash on /data permission checks.
# Key it on the target database: CB_DATA_DIR holds the one-time bootstrap setup
# token file, so two suites running side by side against their own databases would
# otherwise overwrite each other's token and fail bootstrap with a 403.
_DATA_DIR_URL = os.environ.get("CB_TEST_DB_URL") or os.environ.get("CB_DB_URL") or ""
_DATA_DIR_KEY = _DATA_DIR_URL.rsplit("/", 1)[-1] or "default"
os.environ.setdefault("CB_DATA_DIR", f"/tmp/cb-test-data-{_DATA_DIR_KEY}")

# Disable Alembic auto-migration in tests; conftest uses Base.metadata.create_all() instead
os.environ.setdefault("CB_AUTO_MIGRATE", "false")

# v0.2.0: app.db.session requires CB_DB_URL to be postgresql:// at import time.
# Schema uses JSONB (PostgreSQL-only), so tests need a real Postgres or are skipped.
# Default below is for local/test DB only; do not use in production. Set CB_TEST_DB_URL for CI.
os.environ["CB_DB_URL"] = (
    os.environ.get("CB_TEST_DB_URL")
    or os.environ.get("CB_DB_URL")
    or "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"
)

# Test DB URL for fixtures (local/test only; must not contain production secrets).
_TEST_DB_URL_DEFAULT = "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"
TEST_DB_URL = os.environ.get("CB_TEST_DB_URL") or os.environ.get("CB_DB_URL") or _TEST_DB_URL_DEFAULT

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core import (  # noqa: E402
    compat as _compat,  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi import
)
from app.core.rate_limit import limiter  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402

limiter.enabled = False  # Disable rate-limiting during tests
from app.db import models  # noqa: F401 E402 — register models with metadata
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def db_engine():
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
        # metadata.tables, not metadata.sorted_tables: a single
        # `TRUNCATE a, b, c CASCADE` is order-independent by definition, so the
        # topological sort bought nothing -- and it raises
        # CircularDependencyError on the agents -> hardware -> scan_results ->
        # agents foreign-key cycle, which failed the setup of every test taking
        # this fixture (364 errors). The DDL path tolerates that cycle because
        # it can defer constraints; `sorted_tables` cannot, so it was the only
        # place the cycle was fatal.
        tables = ", ".join(table.name for table in Base.metadata.tables.values())
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
    # test DB instead of the production database.
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


def _http_failure(step: str, resp) -> str:
    """Build an assertion message that actually names the failure.

    A bare ``resp.json()["token"]`` turns one broken bootstrap contract into
    dozens of anonymous ``KeyError: 'token'`` tracebacks with the real 422 nowhere
    in sight. Always report the step, the status code and the body.
    """
    body = resp.text
    if len(body) > 2000:
        body = body[:2000] + "... (truncated)"
    return f"{step} failed: HTTP {resp.status_code} {body}"


def _read_setup_token(client) -> str:
    """Obtain the one-time bootstrap setup token the way the product intends.

    Bootstrap is token-gated: the server mints a single-use setup token and either
    takes it from ``CB_SETUP_TOKEN`` or writes it to a 0600 file under
    ``CB_DATA_DIR``. ``GET /bootstrap/status`` publishes that file's path — the
    same signpost the setup wizard shows the operator. Walking that real path (as
    opposed to seeding ``bootstrap_token_hash`` or patching the check) is
    deliberate: the token requirement landing without the fixture noticing is
    exactly what broke every authenticated test here, and this keeps the fixture
    on the hook for the contract.
    """
    env_token = (os.environ.get("CB_SETUP_TOKEN") or "").strip()
    if env_token:
        # Operator-supplied token: the server writes no file in this mode.
        return env_token

    resp = client.get("/api/v1/bootstrap/status")
    assert resp.status_code == 200, _http_failure("GET /api/v1/bootstrap/status", resp)
    status = resp.json()
    assert status.get("needs_bootstrap") is True, (
        "expected an un-bootstrapped app on this test's freshly truncated database, "
        f"but /bootstrap/status reported {status}"
    )
    token_path = status.get("setup_token_path")
    assert token_path, (
        "/bootstrap/status did not report setup_token_path, so the setup token the "
        f"bootstrap endpoint requires cannot be located. Response: {status}"
    )
    token_file = Path(token_path)
    assert token_file.is_file(), (
        f"/bootstrap/status pointed at {token_file} for the setup token but no such "
        "file exists; the server did not write one."
    )
    setup_token = token_file.read_text(encoding="utf-8").strip()
    assert setup_token, f"setup token file {token_file} is empty"
    return setup_token


@pytest.fixture
def auth_headers(client):
    """Bootstrap the app, log in, and return Bearer auth headers.

    Auth is always enabled after bootstrap. Use this fixture in tests that
    need a fully bootstrapped app with valid credentials. Every step is asserted
    with the status code and body, because a silent failure here degrades whole
    test files into confusing downstream errors rather than one clear message.
    """
    bootstrap_resp = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "setup_token": _read_setup_token(client),
            "email": "test@example.com",
            "password": "Secure1234!",
            "theme_preset": "one-dark",
        },
    )
    assert bootstrap_resp.status_code == 200, _http_failure(
        "POST /api/v1/bootstrap/initialize", bootstrap_resp
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "Secure1234!",
        },
    )
    assert login_resp.status_code == 200, _http_failure("POST /api/v1/auth/login", login_resp)
    login_body = login_resp.json()
    assert isinstance(login_body, dict) and login_body.get("token"), (
        f"login succeeded but returned no session token: {login_body}"
    )
    token = login_body["token"]
    csrf_token = client.cookies.get("cb_csrf", "")
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf_token}

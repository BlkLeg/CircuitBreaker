"""
Test suite foundation: PostgreSQL testcontainers, ASGI client, DB fixtures.

Architecture notes:
- pytest_configure sets CB_DB_URL BEFORE any app module is imported, so
  Settings() and create_engine() pick up the testcontainers URL at import time.
- DB session is sync (SessionLocal), not async.
- JWT secret is stored in AppSettings DB row — the app_cfg fixture seeds it.
- NATS and APScheduler degrade gracefully when NATS is unavailable in tests.
"""

import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Testcontainers: start Postgres BEFORE any app import ──────────────────────
_PG_CONTAINER = None


def pytest_configure(config):
    """Spin up Postgres and set env vars before app modules are imported."""
    global _PG_CONTAINER
    from testcontainers.postgres import PostgresContainer

    # TimescaleDB-on-pg16, not vanilla postgres: rollup_worker.py's
    # calculate_daily_rollups uses time_bucket(), a TimescaleDB-only function.
    _PG_CONTAINER = PostgresContainer("timescale/timescaledb:2.14.2-pg16")
    _PG_CONTAINER.start()

    # Settings() is a module-level singleton in config.py — set env before import
    os.environ["CB_DB_URL"] = _PG_CONTAINER.get_connection_url()
    os.environ["CB_JWT_SECRET"] = "ci-test-jwt-secret-minimum-32-chars-xxxx"
    os.environ["CB_VAULT_KEY"] = "hUQwP5Pb5SDdz_8mBBe0aPn7B6K1lItbytzXv7eaGLk="
    os.environ["NATS_AUTH_TOKEN"] = "ci-test-nats-token"
    # The `setup_db` fixture builds schema directly via SQLAlchemy metadata
    # (models.Base.metadata.create_all), not via Alembic. main.py's startup
    # lifespan auto-migrate phase (only exercised once a real ASGI lifespan
    # runs, e.g. via the `ws_client` TestClient fixture) would otherwise try
    # to run migrations against tables that already exist in their final
    # shape and fail/cancel. Tests don't need it either way.
    os.environ["CB_AUTO_MIGRATE"] = "false"

    import psycopg2

    conn = psycopg2.connect(
        _PG_CONTAINER.get_connection_url().replace("postgresql+psycopg2", "postgresql")
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    conn.close()


def pytest_unconfigure(config):
    global _PG_CONTAINER
    if _PG_CONTAINER:
        try:
            _PG_CONTAINER.stop()
        except Exception:
            pass


# ── DB schema ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def setup_db():
    """Create all tables once per session, drop on teardown."""
    from app.db import models  # noqa: F401 — registers all ORM metadata
    from app.db.session import engine

    models.Base.metadata.create_all(bind=engine)
    yield
    models.Base.metadata.drop_all(bind=engine)


# ── AppSettings seed: JWT secret + vault key ──────────────────────────────────


@pytest.fixture(scope="session")
def app_cfg(setup_db):
    """
    Seed AppSettings with test JWT secret and vault key so auth works.
    Session-scoped: runs once per pytest session.
    """
    from app.db.models import AppSettings
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        cfg = session.query(AppSettings).first()
        if cfg is None:
            cfg = AppSettings(id=1)
            session.add(cfg)
        cfg.jwt_secret = os.environ["CB_JWT_SECRET"]
        cfg.auth_enabled = True
        # Vault key stored in env (picked up by vault_service.load_vault_key)
        session.commit()

    # Initialize in-memory vault with test key
    try:
        from app.services.credential_vault import get_vault

        get_vault().reinitialize(os.environ["CB_VAULT_KEY"])
    except Exception:
        pass  # Vault may not be initialized yet; entrypoint handles it


# ── Per-test DB session (rolled back after each test) ─────────────────────────


@pytest.fixture
def db_session(setup_db):
    """
    Per-test DB session using SAVEPOINT-based isolation.

    The outer connection transaction is never committed — even when route
    handlers call session.commit(), SQLAlchemy redirects that to a SAVEPOINT.
    The fixture rolls back the outer transaction on teardown, giving each test
    a clean slate without recreating the schema.
    """
    from sqlalchemy.orm import Session

    from app.db.session import engine

    connection = engine.connect()
    outer_tx = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_tx.rollback()
        connection.close()


@pytest_asyncio.fixture
async def async_db_session(setup_db):
    """Per-test ASYNC DB session (SAVEPOINT-based isolation), mirroring db_session
    above. Needed for code paths that genuinely `await` AsyncSession calls (e.g.
    proxmox_telemetry.py) rather than the sync ORM Session used everywhere else.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.async_session import async_engine

    async with async_engine.connect() as connection:
        outer_tx = await connection.begin()
        session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer_tx.rollback()


# ── ASGI HTTP client ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(db_session, app_cfg):
    """
    Full ASGI test client — real middleware, real JWT validation, real DB writes.
    The get_db dependency is overridden to use the per-test rolled-back session.
    """
    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def ws_client(db_session):
    """Sync TestClient for WebSocket routes — httpx's ASGITransport (used by
    the async `client` fixture) does not support the WS upgrade.

    Unlike `client`, `TestClient` runs the app's real startup lifespan —
    including the Phase 1 `/data` writable-volume check in main.py — so
    CB_DATA_DIR is pointed at a throwaway temp dir for the fixture's
    lifetime; this dev host has no writable `/data` outside a container.

    It also means `await nats_client.connect()` actually runs (the `client`
    fixture's ASGITransport never triggers lifespan, so no prior test in this
    suite has exercised this path). nats-py's client retries the *initial*
    connect indefinitely when `max_reconnect_attempts=-1` (set unconditionally
    in app.core.nats_client), so with no NATS broker reachable on this host
    the lifespan never completes. NATS is unrelated to the agent-enrollment
    handshake this fixture exists for, and the app already degrades to a
    no-op NATS client when unavailable — connect() is stubbed here to make
    that degradation actually apply to the full-lifespan path too, rather
    than changing production reconnect behavior.
    """
    import tempfile
    from unittest.mock import AsyncMock

    from starlette.testclient import TestClient

    from app.core.nats_client import nats_client
    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    original_nats_connect = nats_client.connect
    nats_client.connect = AsyncMock(return_value=None)
    with tempfile.TemporaryDirectory() as tmp_data_dir:
        old_data_dir = os.environ.get("CB_DATA_DIR")
        os.environ["CB_DATA_DIR"] = tmp_data_dir
        try:
            with TestClient(app) as tc:
                yield tc
        finally:
            if old_data_dir is None:
                os.environ.pop("CB_DATA_DIR", None)
            else:
                os.environ["CB_DATA_DIR"] = old_data_dir
    nats_client.connect = original_nats_connect
    app.dependency_overrides.pop(get_db, None)


# ── Model factories ───────────────────────────────────────────────────────────


@pytest.fixture
def factories(db_session):
    from tests.factories import Factories

    return Factories(db_session)


# ── Auth fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(factories):
    return factories.user(role="admin")


@pytest_asyncio.fixture
async def admin_login(client, admin_user):
    """Log in as admin and return (token, csrf_token)."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "TestPassword123!"},
    )
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    token = resp.json()["token"]
    csrf = resp.cookies.get("cb_csrf", "test-csrf-token")
    return token, csrf


@pytest_asyncio.fixture
async def admin_token(admin_login):
    return admin_login[0]


@pytest.fixture
def auth_headers(admin_login):
    """Auth headers including CSRF token for mutating requests."""
    token, csrf = admin_login
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


@pytest.fixture
def viewer_user(factories):
    return factories.user(role="viewer")


@pytest_asyncio.fixture
async def viewer_login(client, viewer_user):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": viewer_user.email, "password": "TestPassword123!"},
    )
    assert resp.status_code == 200, f"Viewer login failed: {resp.text}"
    token = resp.json()["token"]
    csrf = resp.cookies.get("cb_csrf", "test-csrf-token")
    return token, csrf


@pytest_asyncio.fixture
async def viewer_token(viewer_login):
    return viewer_login[0]


@pytest.fixture
def viewer_headers(viewer_login):
    token, csrf = viewer_login
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


# ── Pytest markers ────────────────────────────────────────────────────────────


pytest_plugins = ["pytest_asyncio"]


# ── Rate limiter reset — prevent cross-test pollution ─────────────────────────


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset slowapi's in-memory rate limit counters before every test."""
    try:
        from app.core.rate_limit import limiter

        if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
            limiter._storage.reset()
        elif hasattr(limiter, "reset"):
            limiter.reset()
    except Exception:
        pass  # Non-fatal — tests may still hit limits but won't fail from prior tests


@pytest.fixture
def redis_mock():
    """
    In-memory async Redis stub used by auth token lifecycle tests.

    Returns:
        tuple(get_redis_fn, redis_client_mock, backing_store)
    """

    store: dict[str, str] = {}
    redis_client = AsyncMock()

    async def _setex(key: str, _ttl: int, value: str) -> bool:
        store[key] = value
        return True

    async def _get(key: str):
        return store.get(key)

    async def _delete(key: str) -> int:
        return 1 if store.pop(key, None) is not None else 0

    async def _get_redis():
        return redis_client

    redis_client.setex.side_effect = _setex
    redis_client.get.side_effect = _get
    redis_client.delete.side_effect = _delete

    return _get_redis, redis_client, store

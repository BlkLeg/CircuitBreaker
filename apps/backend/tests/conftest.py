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

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Testcontainers: start Postgres BEFORE any app import ──────────────────────
_PG_CONTAINER = None


def pytest_configure(config):
    """Spin up Postgres and set env vars before app modules are imported."""
    global _PG_CONTAINER
    from testcontainers.postgres import PostgresContainer

    _PG_CONTAINER = PostgresContainer("postgres:16-alpine")
    _PG_CONTAINER.start()

    # Settings() is a module-level singleton in config.py — set env before import
    os.environ["CB_DB_URL"] = _PG_CONTAINER.get_connection_url()
    os.environ["CB_JWT_SECRET"] = "ci-test-jwt-secret-minimum-32-chars-xxxx"
    os.environ["CB_VAULT_KEY"] = "3__S8_NEU_uipJArCvNStY9bMB44fZTwWcw952jZPX0="
    os.environ["NATS_AUTH_TOKEN"] = "ci-test-nats-token"


def pytest_unconfigure(config):
    global _PG_CONTAINER
    if _PG_CONTAINER:
        try:
            _PG_CONTAINER.stop()
        except Exception as exc:
            print(f"Failed to stop test Postgres container (non-fatal): {exc}")


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
    from app.services.credential_vault import get_vault

    get_vault().reinitialize(os.environ["CB_VAULT_KEY"])


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


def pytest_configure_node(node):
    pass


pytest_plugins = ["pytest_asyncio"]


# ── Redis mock — in-memory dict backing for token-based flows ─────────────


@pytest.fixture
def redis_mock():
    """Provide a fake Redis backed by a plain dict for token storage tests.

    Returns ``(get_redis_fn, mock_redis, store)`` where *store* is the
    underlying dict so tests can inspect written keys.
    """
    from unittest.mock import AsyncMock, MagicMock

    store: dict[str, tuple[str, float | None]] = {}

    mock = MagicMock()

    def _get(key):
        entry = store.get(key)
        if entry is None:
            return None
        val, _exp = entry
        return val

    def _set(key, value, ex=None):
        store[key] = (value, ex)

    def _setex(key, ttl, value):
        store[key] = (value, ttl)

    def _delete(key):
        store.pop(key, None)

    mock.get = AsyncMock(side_effect=_get)
    mock.set = AsyncMock(side_effect=_set)
    mock.setex = AsyncMock(side_effect=_setex)
    mock.delete = AsyncMock(side_effect=_delete)

    async def get_redis_fn():
        return mock

    yield get_redis_fn, mock, store


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

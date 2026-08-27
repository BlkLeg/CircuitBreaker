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
import shutil
import tempfile
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

# ── Testcontainers: start Postgres BEFORE any app import ──────────────────────
_PG_CONTAINER = None
# Per-run upload root, created in pytest_configure and removed in
# pytest_unconfigure so the suite never writes into the working tree.
_UPLOADS_TMPDIR: str | None = None
# Per-run data root, same lifecycle as _UPLOADS_TMPDIR above.
_DATA_TMPDIR: str | None = None


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
    os.environ["CB_ALLOW_DEGRADED_DEPENDENCIES"] = "true"
    os.environ["CB_RATE_LIMIT_STORAGE_URL"] = "memory://"
    # The `setup_db` fixture builds schema directly via SQLAlchemy metadata
    # (models.Base.metadata.create_all), not via Alembic. main.py's startup
    # lifespan auto-migrate phase (only exercised once a real ASGI lifespan
    # runs, e.g. via the `ws_client` TestClient fixture) would otherwise try
    # to run migrations against tables that already exist in their final
    # shape and fail/cancel. Tests don't need it either way.
    os.environ["CB_AUTO_MIGRATE"] = "false"

    # Upload root must live outside the working tree. Settings.uploads_dir
    # defaults to the RELATIVE path "data/uploads", which resolves against the
    # backend CWD, so every profile-photo test used to deposit real PNGs into
    # apps/backend/data/uploads/profiles/. That residue makes `git status`
    # useless as a review signal and has already prompted an agent to start
    # deleting tracked files to "clean up". Redirect to a per-run temp dir here,
    # before any app module is imported: uploads_dir is read at import time into
    # module-level constants (auth_service._PROFILES_DIR, main._uploads_dir,
    # api/assets._UPLOADS_DIR, ...), so a fixture-time monkeypatch would be too
    # late to catch them.
    global _UPLOADS_TMPDIR
    _UPLOADS_TMPDIR = tempfile.mkdtemp(prefix="cb-test-uploads-")
    os.environ["UPLOADS_DIR"] = _UPLOADS_TMPDIR

    # Same problem as UPLOADS_DIR, one directory up, and worse in consequence
    # (B37). `vault_service._data_dir()` is `CB_DATA_DIR or Path.cwd()/"data"`,
    # and the suite's cwd is apps/backend -- so a run with CB_DATA_DIR unset
    # generated a REAL Fernet key and wrote it to apps/backend/data/.env in the
    # working tree. It is gitignored, so it never showed up in `git status`; it
    # just sat there, 0600, indistinguishable from a developer's own key, and a
    # later run would load it instead of generating a fresh one.
    #
    # The same variable now also decides where a snapshot stages its work
    # (services/backup/snapshot._staging_root, default /var/lib/circuitbreaker)
    # and where certificates and the CVE database land, so leaving it unset
    # points several code paths at real system locations. One redirect covers
    # all of them, and it has to happen here rather than in a fixture because
    # these are read at import time into module-level constants.
    global _DATA_TMPDIR
    _DATA_TMPDIR = tempfile.mkdtemp(prefix="cb-test-data-")
    os.environ["CB_DATA_DIR"] = _DATA_TMPDIR

    import psycopg2

    conn = psycopg2.connect(
        _PG_CONTAINER.get_connection_url().replace("postgresql+psycopg2", "postgresql")
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    conn.close()


def pytest_unconfigure(config):
    global _PG_CONTAINER, _UPLOADS_TMPDIR, _DATA_TMPDIR
    if _PG_CONTAINER:
        try:
            _PG_CONTAINER.stop()
        except Exception:
            pass
    if _UPLOADS_TMPDIR:
        # Only ever removes the directory this process created via mkdtemp.
        shutil.rmtree(_UPLOADS_TMPDIR, ignore_errors=True)
        _UPLOADS_TMPDIR = None
    if _DATA_TMPDIR:
        # Same guarantee: this process created it, so this process removes it.
        # It holds a generated vault key, which is exactly why it does not
        # outlive the run.
        shutil.rmtree(_DATA_TMPDIR, ignore_errors=True)
        _DATA_TMPDIR = None


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


def _reaped_models() -> tuple[type, ...]:
    """Tables tests legitimately commit outside the per-test transaction.

    Ordered so a child is deleted before whatever it points at: monitor rows
    name a hardware target, and hardware and users can carry a tenant.
    """
    from app.db.models import Agent, Hardware, MonitorItem, Tenant, User

    return (MonitorItem, Agent, Hardware, User, Tenant)


def _committed_ids() -> dict[str, set[int]]:
    """Ids visible to a *fresh* connection, i.e. genuinely committed."""
    from app.db.session import SessionLocal

    with SessionLocal() as probe:
        return {
            model.__name__: {row[0] for row in probe.execute(select(model.id)).all()}
            for model in _reaped_models()
        }


def _reap_agents_committed_outside_the_test(known_ids: dict[str, set[int]]) -> None:
    """Delete rows this test committed on some *other* connection.

    Several agent suites must commit for real rather than write through
    `db_session`: `test_ws_agents_link.py::_active_agent_with_key` exists
    because `link_stream` opens its own `SessionLocal()` and therefore cannot
    see `db_session`'s uncommitted SAVEPOINT, and the enrollment-cap tests
    genuinely race independent sessions. Those rows are outside the outer
    transaction, so the rollback below cannot undo them, and they survive into
    every later test in the session — which is what made
    `tests/api/test_agents_api.py::test_list_agents_returns_summaries` (it
    asserts the agent list equals exactly the two rows it created) fail
    whenever a ws suite ran first.

    This *must* run after `outer_tx.rollback()`, which is why it lives in
    `db_session` and not in `ws_client`. A route handler running under the
    dependency override updates those committed rows through `db_session`,
    taking row locks inside the still-open outer transaction. `ws_client`
    depends on `db_session`, so it is torn down *first* — deleting from there
    blocks forever on a lock held by a connection that is `idle in
    transaction` and will not be rolled back until the fixture below finishes.
    (Observed exactly that: `DELETE FROM agents WHERE agents.id IN (25)`
    waiting on `Lock/transactionid` for over an hour.)

    Monitors are the same story as agents: `test_monitor_stream_auth.py` commits
    a hardware row and a monitor per case because the stream handler opens its
    own session and cannot see the SAVEPOINT either. Left behind, those rows
    broke every later test that counts monitors — `test_monitor_targets.py`,
    the scheduler suites, `test_discovery_auto_monitor.py` — but only in a full
    run, which is the worst way to find out.
    """
    from app.db.session import SessionLocal

    with SessionLocal() as reaper:
        deleted = False
        for model in _reaped_models():
            known = known_ids.get(model.__name__, set())
            leaked = [
                row[0] for row in reaper.execute(select(model.id)).all() if row[0] not in known
            ]
            if leaked:
                reaper.execute(delete(model).where(model.id.in_(leaked)))
                deleted = True
        if deleted:
            reaper.commit()


@pytest.fixture
def db_session(setup_db):
    """
    Per-test DB session using SAVEPOINT-based isolation.

    The outer connection transaction is never committed — even when route
    handlers call session.commit(), SQLAlchemy redirects that to a SAVEPOINT.
    The fixture rolls back the outer transaction on teardown, giving each test
    a clean slate without recreating the schema.

    Rows committed on *other* connections escape that rollback; agent rows are
    the case tests actually hit, so they are reaped explicitly on teardown —
    see _reap_agents_committed_outside_the_test.
    """
    from sqlalchemy.orm import Session

    from app.db.session import engine

    known_ids = _committed_ids()
    connection = engine.connect()
    outer_tx = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_tx.rollback()
        connection.close()
        _reap_agents_committed_outside_the_test(known_ids)


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

    original_nats_connect = nats_client.connect
    old_data_dir = os.environ.get("CB_DATA_DIR")
    with tempfile.TemporaryDirectory() as tmp_data_dir:
        # All three pieces of shared/global state this fixture mutates —
        # dependency override, NATS stub, CB_DATA_DIR — are set and torn down
        # inside one try/finally so a mid-test exception (anywhere in the
        # `with TestClient(app)` block below) can never leak any of them onto
        # subsequent tests in the session.
        try:
            app.dependency_overrides[get_db] = override_get_db
            nats_client.connect = AsyncMock(return_value=None)
            os.environ["CB_DATA_DIR"] = tmp_data_dir
            # NB: agent rows a ws test commits outside the savepoint are
            # reaped by the db_session fixture, not here — see the comment on
            # _reap_agents_committed_outside_the_test for why the cleanup
            # cannot live in this fixture.
            with TestClient(app) as tc:
                yield tc
        finally:
            app.dependency_overrides.pop(get_db, None)
            nats_client.connect = original_nats_connect
            if old_data_dir is None:
                os.environ.pop("CB_DATA_DIR", None)
            else:
                os.environ["CB_DATA_DIR"] = old_data_dir


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


@pytest.fixture
def editor_user(factories):
    return factories.user(role="editor")


@pytest_asyncio.fixture
async def editor_login(client, editor_user):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": editor_user.email, "password": "TestPassword123!"},
    )
    assert resp.status_code == 200, f"Editor login failed: {resp.text}"
    token = resp.json()["token"]
    csrf = resp.cookies.get("cb_csrf", "test-csrf-token")
    return token, csrf


@pytest.fixture
def editor_headers(editor_login):
    token, csrf = editor_login
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


@pytest.fixture
def nmap_enabled(db_session):
    """Turn on the ``nmap_enabled`` opt-in for tests that exercise nmap scan paths.

    ``discovery_service.create_scan_job`` refuses any scan whose ``scan_types``
    require nmap unless ``AppSettings.nmap_enabled`` is set — an opt-in gate
    added in 11dcb910 (migration 0079) that defaults to False. The scan API
    flattens that refusal into ``422 Invalid scan request parameters``, the
    same status the CIDR/argument validators produce.

    That collision is why this fixture exists rather than the tests simply
    asserting 422: the discovery/security tests predate the gate, and with the
    flag off they no longer reach validation at all. Some then *failed*
    (``test_create_scan_valid_cidr``), but the more dangerous ones *passed
    vacuously* — ``test_slash8_cidr_returns_422`` and
    ``test_nmap_shell_metacharacter_rejected`` were getting their 422 from the
    disabled flag, so neither the M-17 CIDR-size limit nor the shell-injection
    rejection was actually being verified. Enabling the flag restores what
    those tests were written to check.

    The write lands on ``db_session``'s SAVEPOINT and is rolled back with the
    rest of the test, so it cannot leak into the session.
    """
    from app.services.settings_service import get_or_create_settings

    cfg = get_or_create_settings(db_session)
    cfg.nmap_enabled = True
    db_session.flush()
    return cfg

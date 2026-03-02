from app.core import compat as _compat  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi/sentry_sdk import
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import engine, Base, SessionLocal
from app.db import models  # noqa: F401 — import to register all model metadata with Base
from app.api import hardware, compute_units, services, storage, networks, misc, docs, graph, search, logs, auth, clusters, external_nodes, bootstrap, catalog, telemetry as telemetry_api, categories, environments
from app.api.ip_check import router as ip_check_router
from app.api.settings import router as settings_router
from app.api.branding import router as branding_router
from app.api.admin import router as admin_router
from app.api.security_status import router as security_router
from app.api.metrics import router as metrics_router
from app.api.timezones import router as timezones_router
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter
import sentry_sdk

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=1.0,
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
    )

_SQLITE_SCHEME = "sqlite:///"
_logger = logging.getLogger(__name__)


def _get_columns(conn, table: str) -> list[str]:
    """Return the column names for a SQLite table."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]  # noqa: S608


def _backfill_log_timestamps(db) -> None:
    """Backfill created_at_utc for log rows that still have NULL in that column.

    Reads from the `timestamp` DateTime column (set at insert time by write_log)
    and converts it to a UTC ISO-8601 string.  Rows where `timestamp` is None
    or cannot be parsed receive the epoch sentinel "1970-01-01T00:00:00+00:00".

    Accepts either an ORM Session (test fixtures) or a raw SQLite connection
    (migration path).
    """
    from datetime import datetime, timezone as _tz
    from sqlalchemy import text

    _EPOCH = "1970-01-01T00:00:00+00:00"
    rows = db.execute(
        text("SELECT id, timestamp FROM logs WHERE created_at_utc IS NULL")
    ).fetchall()
    for log_id, ts in rows:
        val = _EPOCH
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts))
                val = dt.isoformat() if dt.tzinfo else dt.replace(tzinfo=_tz.utc).isoformat()
            except (ValueError, TypeError):
                pass
        db.execute(
            text("UPDATE logs SET created_at_utc = :val WHERE id = :id"),
            {"val": val, "id": log_id},
        )
    db.commit()


def _run_migrations(conn) -> None:
    """Apply lightweight schema migrations to an existing SQLite database."""
    # compute_units.icon_slug
    cu_cols = _get_columns(conn, "compute_units")
    if "icon_slug" not in cu_cols:
        conn.execute("ALTER TABLE compute_units ADD COLUMN icon_slug TEXT")
    # services.hardware_id
    svc_cols = _get_columns(conn, "services")
    if "hardware_id" not in svc_cols:
        conn.execute("ALTER TABLE services ADD COLUMN hardware_id INTEGER REFERENCES hardware(id)")
    # services.icon_slug (re-fetch after potential hardware_id add)
    svc_cols = _get_columns(conn, "services")
    if "icon_slug" not in svc_cols:
        conn.execute("ALTER TABLE services ADD COLUMN icon_slug TEXT")
    # services.status
    svc_cols = _get_columns(conn, "services")
    if "status" not in svc_cols:
        conn.execute("ALTER TABLE services ADD COLUMN status TEXT")
    # hardware.ip_address / wan_uplink
    hw_cols = _get_columns(conn, "hardware")
    if "ip_address" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN ip_address TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "wan_uplink" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN wan_uplink TEXT")
    # hardware.cpu_brand / compute_units.cpu_brand
    hw_cols = _get_columns(conn, "hardware")
    if "cpu_brand" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN cpu_brand TEXT")
    cu_cols = _get_columns(conn, "compute_units")
    if "cpu_brand" not in cu_cols:
        conn.execute("ALTER TABLE compute_units ADD COLUMN cpu_brand TEXT")
    # networks.gateway_hardware_id
    net_cols = _get_columns(conn, "networks")
    if "gateway_hardware_id" not in net_cols:
        conn.execute("ALTER TABLE networks ADD COLUMN gateway_hardware_id INTEGER REFERENCES hardware(id)")
    # app_settings: environments, categories, dock_order
    settings_cols = _get_columns(conn, "app_settings")
    if "environments" not in settings_cols:
        conn.execute('ALTER TABLE app_settings ADD COLUMN environments TEXT DEFAULT \'["prod","staging","dev"]\'')
    if "categories" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN categories TEXT DEFAULT '[]'")
    if "dock_order" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN dock_order TEXT")
    if "locations" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN locations TEXT DEFAULT '[]'")
    # hardware.vendor_icon_slug
    hw_cols = _get_columns(conn, "hardware")
    if "vendor_icon_slug" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN vendor_icon_slug TEXT")
    # Fix services.compute_id NOT NULL constraint — must be nullable
    svc_schema = conn.execute("PRAGMA table_info(services)").fetchall()
    compute_id_col = next((c for c in svc_schema if c[1] == "compute_id"), None)
    if compute_id_col and compute_id_col[3] == 1:  # notnull == 1
        _logger.info("Migrating services table: making compute_id nullable")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""
            CREATE TABLE services_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR NOT NULL,
                slug VARCHAR UNIQUE NOT NULL,
                compute_id INTEGER REFERENCES compute_units(id),
                hardware_id INTEGER REFERENCES hardware(id),
                category VARCHAR,
                url VARCHAR,
                ports VARCHAR,
                description TEXT,
                environment VARCHAR,
                created_at DATETIME,
                updated_at DATETIME
            )
        """)
        conn.execute("""
            INSERT INTO services_new
                (id, name, slug, compute_id, hardware_id, category, url, ports,
                 description, environment, created_at, updated_at)
            SELECT id, name, slug, compute_id, hardware_id, category, url, ports,
                   description, environment, created_at, updated_at
            FROM services
        """)
        conn.execute("DROP TABLE services")
        conn.execute("ALTER TABLE services_new RENAME TO services")
        conn.execute("PRAGMA foreign_keys=ON")
    # services.ip_address
    svc_cols = _get_columns(conn, "services")
    if "ip_address" not in svc_cols:
        conn.execute("ALTER TABLE services ADD COLUMN ip_address TEXT")
    # logs.status_code
    log_cols = _get_columns(conn, "logs")
    if "status_code" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN status_code INTEGER")
    if "actor_gravatar_hash" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN actor_gravatar_hash TEXT")
    # storage.used_gb
    st_cols = _get_columns(conn, "storage")
    if "used_gb" not in st_cols:
        conn.execute("ALTER TABLE storage ADD COLUMN used_gb INTEGER")
    # app_settings: auth fields
    settings_cols = _get_columns(conn, "app_settings")
    if "auth_enabled" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN auth_enabled BOOLEAN DEFAULT FALSE")
    if "jwt_secret" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN jwt_secret TEXT")
    if "session_timeout_hours" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN session_timeout_hours INTEGER DEFAULT 24")
    # docs.body_html
    doc_cols = _get_columns(conn, "docs")
    if "body_html" not in doc_cols:
        conn.execute("ALTER TABLE docs ADD COLUMN body_html TEXT")
    # app_settings: branding fields
    settings_cols = _get_columns(conn, "app_settings")
    if "app_name" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN app_name TEXT DEFAULT 'Circuit Breaker'")
    if "favicon_path" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN favicon_path TEXT")
    if "login_logo_path" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN login_logo_path TEXT")
    if "primary_color" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN primary_color TEXT DEFAULT '#00d4ff'")
    if "accent_colors" not in settings_cols:
        conn.execute('ALTER TABLE app_settings ADD COLUMN accent_colors TEXT DEFAULT \'["#ff6b6b","#4ecdc4"]\'')
    # app_settings: advanced theming
    settings_cols = _get_columns(conn, "app_settings")
    if "theme_preset" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN theme_preset TEXT DEFAULT 'cyberpunk-neon'")
    if "custom_colors" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN custom_colors TEXT")
    # storage.icon_slug
    st_cols = _get_columns(conn, "storage")
    if "icon_slug" not in st_cols:
        conn.execute("ALTER TABLE storage ADD COLUMN icon_slug TEXT")
    # networks.icon_slug
    net_cols = _get_columns(conn, "networks")
    if "icon_slug" not in net_cols:
        conn.execute("ALTER TABLE networks ADD COLUMN icon_slug TEXT")
    # misc_items.icon_slug
    misc_cols = _get_columns(conn, "misc_items")
    if "icon_slug" not in misc_cols:
        conn.execute("ALTER TABLE misc_items ADD COLUMN icon_slug TEXT")
    # app_settings: dock_hidden_items + show_page_hints
    settings_cols = _get_columns(conn, "app_settings")
    if "dock_hidden_items" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN dock_hidden_items TEXT")
    if "show_page_hints" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN show_page_hints BOOLEAN DEFAULT TRUE")
    # hardware_clusters + hardware_cluster_members (new tables — safe to CREATE IF NOT EXISTS)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hardware_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            environment TEXT,
            location TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hardware_cluster_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL REFERENCES hardware_clusters(id) ON DELETE CASCADE,
            hardware_id INTEGER NOT NULL REFERENCES hardware(id) ON DELETE CASCADE,
            role TEXT,
            UNIQUE (cluster_id, hardware_id)
        )
    """)
    # external_nodes + external_node_networks + service_external_nodes (off-prem / cloud)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS external_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT,
            kind TEXT,
            region TEXT,
            ip_address TEXT,
            icon_slug TEXT,
            notes TEXT,
            environment TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS external_node_networks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_node_id INTEGER NOT NULL REFERENCES external_nodes(id) ON DELETE CASCADE,
            network_id INTEGER NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
            link_type TEXT,
            notes TEXT,
            UNIQUE (external_node_id, network_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS service_external_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
            external_node_id INTEGER NOT NULL REFERENCES external_nodes(id) ON DELETE CASCADE,
            purpose TEXT,
            UNIQUE (service_id, external_node_id)
        )
    """)
    # app_settings: show_external_nodes_on_map
    settings_cols = _get_columns(conn, "app_settings")
    if "show_external_nodes_on_map" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN show_external_nodes_on_map BOOLEAN DEFAULT TRUE")
    # v0.1.2: hardware vendor catalog + telemetry fields
    hw_cols = _get_columns(conn, "hardware")
    if "vendor_catalog_key" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN vendor_catalog_key TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "model_catalog_key" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN model_catalog_key TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "u_height" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN u_height INTEGER")
    hw_cols = _get_columns(conn, "hardware")
    if "rack_unit" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN rack_unit INTEGER")
    hw_cols = _get_columns(conn, "hardware")
    if "telemetry_config" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN telemetry_config TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "telemetry_data" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN telemetry_data TEXT DEFAULT '{}'")
    hw_cols = _get_columns(conn, "hardware")
    if "telemetry_status" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN telemetry_status TEXT DEFAULT 'unknown'")
    hw_cols = _get_columns(conn, "hardware")
    if "telemetry_last_polled" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN telemetry_last_polled TIMESTAMP")
    # v0.1.3: categories table + category_id FK on services
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
            color      TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','utc'))
        )
    """)
    svc_cols = _get_columns(conn, "services")
    if "category_id" not in svc_cols:
        conn.execute(
            "ALTER TABLE services ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL"
        )
    # Backfill: migrate legacy category strings → category_id
    rows = conn.execute(
        "SELECT id, category FROM services WHERE category IS NOT NULL AND category_id IS NULL"
    ).fetchall()
    for svc_id, cat_name in rows:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, datetime('now','utc'))",
            (cat_name,),
        )
        cat_row = conn.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (cat_name,)
        ).fetchone()
        if cat_row:
            conn.execute(
                "UPDATE services SET category_id = ? WHERE id = ?", (cat_row[0], svc_id)
            )
    # v0.1.4: environments table + environment_id FK on hardware/compute_units/services
    conn.execute("""
        CREATE TABLE IF NOT EXISTS environments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
            color      TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','utc'))
        )
    """)
    for table in ("hardware", "compute_units", "services"):
        tbl_cols = _get_columns(conn, table)
        if "environment_id" not in tbl_cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN environment_id INTEGER REFERENCES environments(id) ON DELETE SET NULL"  # noqa: S608
            )
    # Backfill compute_units and services (hardware has no legacy environment column)
    backfill_count = 0
    for table in ("compute_units", "services"):
        rows = conn.execute(
            f"SELECT id, environment FROM {table} WHERE environment IS NOT NULL AND environment_id IS NULL"  # noqa: S608
        ).fetchall()
        for row_id, env_name in rows:
            conn.execute(
                "INSERT OR IGNORE INTO environments (name, created_at) VALUES (?, datetime('now','utc'))",
                (env_name,),
            )
            env_row = conn.execute(
                "SELECT id FROM environments WHERE name = ? COLLATE NOCASE", (env_name,)
            ).fetchone()
            if env_row:
                conn.execute(
                    f"UPDATE {table} SET environment_id = ? WHERE id = ?",  # noqa: S608
                    (env_row[0], row_id),
                )
                backfill_count += 1
    _logger.info("Environments backfill: %d rows updated", backfill_count)
    # v0.1.5: services.ports_json — structured port bindings replacing freeform string
    import re as _re
    import json as _json
    svc_cols = _get_columns(conn, "services")
    if "ports_json" not in svc_cols:
        conn.execute("ALTER TABLE services ADD COLUMN ports_json TEXT")
    # Backfill: parse legacy ports string into structured JSON array
    rows = conn.execute(
        "SELECT id, ports FROM services WHERE ports IS NOT NULL AND ports_json IS NULL"
    ).fetchall()
    for svc_id, ports_str in rows:
        entries = []
        for token in [t.strip() for t in ports_str.split(",") if t.strip()]:
            m = _re.match(r"^(\d+)/(\w+)$", token)
            if m:
                entries.append({"port": int(m.group(1)), "protocol": m.group(2), "ip": None})
            elif _re.match(r"^\d+$", token):
                entries.append({"port": int(token), "protocol": "tcp", "ip": None})
            else:
                entries.append({"port": None, "protocol": None, "ip": None, "raw": token})
        conn.execute(
            "UPDATE services SET ports_json = ? WHERE id = ?",
            (_json.dumps(entries), svc_id),
        )
    _logger.info("ports_json backfill: %d service rows processed", len(rows))

    # v0.1.6: logs.created_at_utc — reliable UTC ISO 8601 string for frontend display
    from datetime import datetime, timezone as _tz
    log_cols = _get_columns(conn, "logs")
    if "created_at_utc" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN created_at_utc TEXT")
    _EPOCH = "1970-01-01T00:00:00+00:00"
    log_rows = conn.execute(
        "SELECT id, timestamp FROM logs WHERE created_at_utc IS NULL"
    ).fetchall()
    for log_id, ts in log_rows:
        val = _EPOCH
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts))
                val = dt.isoformat() if dt.tzinfo else dt.replace(tzinfo=_tz.utc).isoformat()
            except (ValueError, TypeError):
                pass
        conn.execute("UPDATE logs SET created_at_utc = ? WHERE id = ?", (val, log_id))
    _logger.info("Log timestamp backfill: %d rows updated", len(log_rows))

    # v0.1.6: app_settings.timezone — IANA timezone preference
    settings_cols = _get_columns(conn, "app_settings")
    if "timezone" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'")

    # Feature 6: audit log structured columns
    log_cols = _get_columns(conn, "logs")
    if "actor_id" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN actor_id INTEGER")
    log_cols = _get_columns(conn, "logs")
    if "actor_name" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN actor_name TEXT NOT NULL DEFAULT 'admin'")
    log_cols = _get_columns(conn, "logs")
    if "entity_name" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN entity_name TEXT")
    log_cols = _get_columns(conn, "logs")
    if "diff" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN diff TEXT")
    log_cols = _get_columns(conn, "logs")
    if "severity" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN severity TEXT NOT NULL DEFAULT 'info'")
    _logger.info("Audit log schema: structured columns present")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the data directory exists before SQLite tries to create the db file
    db_url = settings.database_url
    if db_url.startswith(_SQLITE_SCHEME):
        db_path = db_url.replace(_SQLITE_SCHEME, "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # Create all tables on startup (v1 — no alembic migrations yet)
    Base.metadata.create_all(bind=engine)
    # Lightweight migrations: add new columns to existing SQLite DBs
    if db_url.startswith(_SQLITE_SCHEME):
        import sqlite3
        db_path = db_url.replace(_SQLITE_SCHEME, "")
        if Path(db_path).exists():
            with sqlite3.connect(db_path) as conn:
                _run_migrations(conn)
    try:
        from app.services.settings_service import get_or_create_settings

        with SessionLocal() as db:
            cfg = get_or_create_settings(db)
            user_count = db.query(models.User).count()
            _logger.info(
                "Bootstrap status: needs_bootstrap=%s user_count=%s auth_enabled=%s",
                user_count == 0,
                user_count,
                bool(cfg.auth_enabled),
            )
    except Exception as exc:
        _logger.warning("Bootstrap status logging failed: %s", exc)
    # Ensure all upload subdirectories exist on the persistent volume
    _base = Path(settings.uploads_dir)
    (_base / "icons").mkdir(parents=True, exist_ok=True)
    (_base / "profiles").mkdir(parents=True, exist_ok=True)
    (_base / "branding").mkdir(parents=True, exist_ok=True)
    (_base / "docs").mkdir(parents=True, exist_ok=True)
    yield



app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Attach rate-limiter to app state so slowapi can use it
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

def _error_json(error_code: str, detail: object, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error_code, "detail": detail})


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Convert domain-level AppError subclasses to structured JSON responses."""
    _logger.info("AppError [%s %s]: %s", request.method, request.url.path, exc.message)
    return _error_json(exc.error_code, exc.message, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert Pydantic validation errors to a consistent schema."""
    errors = [
        {"field": ".".join(str(loc) for loc in e["loc"]), "msg": e["msg"]}
        for e in exc.errors()
    ]
    return _error_json("validation_error", errors, 422)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the full traceback server-side, return a safe 500 body."""
    _logger.exception(
        "Unhandled exception [%s %s]", request.method, request.url.path, exc_info=exc
    )
    sentry_sdk.capture_exception(exc)
    return _error_json("internal_error", "An unexpected error occurred.", 500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(hardware.router, prefix=settings.api_prefix)
app.include_router(compute_units.router, prefix=settings.api_prefix)
app.include_router(services.router, prefix=settings.api_prefix)
app.include_router(storage.router, prefix=settings.api_prefix)
app.include_router(networks.router, prefix=settings.api_prefix)
app.include_router(misc.router, prefix=settings.api_prefix)
app.include_router(docs.router, prefix=settings.api_prefix)
app.include_router(graph.router, prefix=settings.api_prefix)
app.include_router(search.router, prefix=settings.api_prefix)
app.include_router(settings_router, prefix=settings.api_prefix)
app.include_router(logs.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(bootstrap.router, prefix=settings.api_prefix)
app.include_router(branding_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(security_router, prefix=settings.api_prefix)
app.include_router(clusters.router, prefix=settings.api_prefix)
app.include_router(external_nodes.router, prefix=settings.api_prefix)
app.include_router(external_nodes._rel_router, prefix=settings.api_prefix)
app.include_router(metrics_router, prefix=settings.api_prefix)
app.include_router(catalog.router, prefix=settings.api_prefix)
app.include_router(telemetry_api.router, prefix=settings.api_prefix)
app.include_router(categories.router, prefix=settings.api_prefix)
app.include_router(environments.router, prefix=settings.api_prefix)
app.include_router(ip_check_router, prefix=settings.api_prefix)
app.include_router(timezones_router, prefix=settings.api_prefix)


# Serve all user-uploaded content. Directories are derived from settings.uploads_dir
# so that UPLOADS_DIR=/data/uploads in Docker lands everything on the persistent volume.
_uploads_base = Path(settings.uploads_dir)

_user_icons_path = _uploads_base / "icons"
_user_icons_path.mkdir(parents=True, exist_ok=True)
app.mount("/user-icons", StaticFiles(directory=_user_icons_path), name="user-icons")

_profile_photos_path = _uploads_base / "profiles"
_profile_photos_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/profiles", StaticFiles(directory=_profile_photos_path), name="profile-photos")

_doc_uploads_path = _uploads_base / "docs"
_doc_uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/docs", StaticFiles(directory=_doc_uploads_path), name="doc-uploads")

_branding_path = _uploads_base / "branding"
_branding_path.mkdir(parents=True, exist_ok=True)
app.mount("/branding", StaticFiles(directory=_branding_path), name="branding")


@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0


@app.api_route(f"{settings.api_prefix}/health", methods=["GET", "HEAD"])
def health(request: Request):
    # HEAD is used by wget --spider (Docker HEALTHCHECK) and Cloudflare health probes.
    # FastAPI/Starlette do not auto-register HEAD for @app.get routes, so it must be
    # declared explicitly here to prevent the SPA catch-all from swallowing it as a 404.
    if request.method == "HEAD":
        return Response(status_code=200)
    return {"status": "ok", "version": settings.app_version}

# Serve React Frontend (Static Files)
# We check if the static directory exists (it should in Docker)
static_path = Path(settings.static_dir)
if static_path.exists():
    # Mount assets, etc.
    app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")

    # You might check contents of dist to see if there are other top-level folders/files to serve specifically,
    # or just serve everything. Mounting "/" as StaticFiles can interfere with API routes if not careful.
    # A common pattern for SPAs:
    
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    async def serve_spa(full_path: str, request: Request):
        # API routes should have been matched earlier; return a proper 404 if somehow reached here
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Prevent path traversal: resolve canonical paths and verify the result
        # stays within the static root before serving any file.
        static_root = static_path.resolve()
        resolved = (static_path / full_path).resolve()
        if not resolved.is_relative_to(static_root):
            raise HTTPException(status_code=404, detail="Not Found")

        # HEAD requests (Cloudflare health probes, curl -I) — return headers only
        if request.method == "HEAD":
            return Response(status_code=200, media_type="text/html")

        if resolved.is_file():
            return FileResponse(resolved)

        # Fallback to index.html for client-side routing
        return HTMLResponse((static_path / "index.html").read_text(encoding="utf-8"))
else:
    _logger.debug("Static directory %s not found — frontend not served (normal in dev)", static_path)
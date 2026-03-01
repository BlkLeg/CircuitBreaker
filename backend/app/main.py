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
from app.api import hardware, compute_units, services, storage, networks, misc, docs, graph, search, logs, auth, clusters, external_nodes, bootstrap
from app.api.settings import router as settings_router
from app.api.branding import router as branding_router
from app.api.admin import router as admin_router
from app.api.security_status import router as security_router
from app.api.metrics import router as metrics_router
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter

_SQLITE_SCHEME = "sqlite:///"
_logger = logging.getLogger(__name__)


def _get_columns(conn, table: str) -> list[str]:
    """Return the column names for a SQLite table."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]  # noqa: S608


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
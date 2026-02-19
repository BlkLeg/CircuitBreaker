from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import engine, Base
from app.db import models  # noqa: F401 — import to register all model metadata with Base
from app.api import hardware, compute_units, services, storage, networks, misc, docs, graph, search, logs
from app.api.settings import router as settings_router
from app.middleware.logging_middleware import LoggingMiddleware

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
    # app_settings: environments, categories, dock_order
    settings_cols = _get_columns(conn, "app_settings")
    if "environments" not in settings_cols:
        conn.execute('ALTER TABLE app_settings ADD COLUMN environments TEXT DEFAULT \'["prod","staging","dev"]\'')
    if "categories" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN categories TEXT DEFAULT '[]'")
    if "dock_order" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN dock_order TEXT")
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
    # Ensure user-icons upload dir exists
    Path("data/user-icons").mkdir(parents=True, exist_ok=True)
    yield



app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)
app.add_middleware(LoggingMiddleware)

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


# Always serve user-uploaded icons, regardless of whether the SPA is built
_user_icons_path = Path("data/user-icons")
_user_icons_path.mkdir(parents=True, exist_ok=True)
app.mount("/user-icons", StaticFiles(directory=_user_icons_path), name="user-icons")

# Serve React Frontend (Static Files)
# We check if the static directory exists (it should in Docker)
static_path = Path(settings.static_dir)
if static_path.exists():
    # Mount assets, etc.
    app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")

    # You might check contents of dist to see if there are other top-level folders/files to serve specifically,
    # or just serve everything. Mounting "/" as StaticFiles can interfere with API routes if not careful.
    # A common pattern for SPAs:
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # API routes should have been matched earlier; return a proper 404 if somehow reached here
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Prevent path traversal: resolve canonical paths and verify the result
        # stays within the static root before serving any file.
        static_root = static_path.resolve()
        resolved = (static_path / full_path).resolve()
        if not resolved.is_relative_to(static_root):
            raise HTTPException(status_code=404, detail="Not Found")

        if resolved.is_file():
            return FileResponse(resolved)

        # Fallback to index.html for client-side routing
        return HTMLResponse((static_path / "index.html").read_text(encoding="utf-8"))
else:
    _logger.debug("Static directory %s not found — frontend not served (normal in dev)", static_path)


@app.get(f"{settings.api_prefix}/health")
def health():
    return {"status": "ok", "version": settings.app_version}

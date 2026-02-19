from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import engine, Base
from app.db import models  # noqa: F401 — import to register all model metadata with Base
from app.api import hardware, compute_units, services, storage, networks, misc, docs, graph, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the data directory exists before SQLite tries to create the db file
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # Create all tables on startup (v1 — no alembic migrations yet)
    Base.metadata.create_all(bind=engine)
    # Lightweight migrations: add new columns to existing SQLite DBs
    if db_url.startswith("sqlite:///"):
        import sqlite3
        db_path = db_url.replace("sqlite:///", "")
        if Path(db_path).exists():
            with sqlite3.connect(db_path) as conn:
                # compute_units.icon_slug
                cu_cols = [r[1] for r in conn.execute("PRAGMA table_info(compute_units)").fetchall()]
                if "icon_slug" not in cu_cols:
                    conn.execute("ALTER TABLE compute_units ADD COLUMN icon_slug TEXT")
                # services.hardware_id
                svc_cols = [r[1] for r in conn.execute("PRAGMA table_info(services)").fetchall()]
                if "hardware_id" not in svc_cols:
                    conn.execute("ALTER TABLE services ADD COLUMN hardware_id INTEGER REFERENCES hardware(id)")
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hardware.router, prefix=settings.api_prefix)
app.include_router(compute_units.router, prefix=settings.api_prefix)
app.include_router(services.router, prefix=settings.api_prefix)
app.include_router(storage.router, prefix=settings.api_prefix)
app.include_router(networks.router, prefix=settings.api_prefix)
app.include_router(misc.router, prefix=settings.api_prefix)
app.include_router(docs.router, prefix=settings.api_prefix)
app.include_router(graph.router, prefix=settings.api_prefix)
app.include_router(search.router, prefix=settings.api_prefix)


# Serve React Frontend (Static Files)
# We check if the static directory exists (it should in Docker)
static_path = Path(settings.static_dir)
if static_path.exists():
    # Mount assets, etc.
    app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")
    # Serve user-uploaded icons
    user_icons_path = Path("data/user-icons")
    user_icons_path.mkdir(parents=True, exist_ok=True)
    app.mount("/user-icons", StaticFiles(directory=user_icons_path), name="user-icons")

    # You might check contents of dist to see if there are other top-level folders/files to serve specifically,
    # or just serve everything. Mounting "/" as StaticFiles can interfere with API routes if not careful.
    # A common pattern for SPAs:
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Allow API routes to pass through (though FastAPI router order usually handles this if defined first)
        if full_path.startswith("api/"):
             return {"error": "Not Found", "status": 404}
        
        # Check if file exists in static dir
        file_path = static_path / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path) # Need to import FileResponse
        
        # Fallback to index.html for client-side routing
        return HTMLResponse((static_path / "index.html").read_text(encoding="utf-8"))
else:
    print(f"WARNING: Static directory {static_path} does not exist. Frontend will not be served.")


@app.get(f"{settings.api_prefix}/health")
def health():
    return {"status": "ok", "version": settings.app_version}

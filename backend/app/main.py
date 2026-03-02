from app.core import compat as _compat  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi import
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
from app.api import rack as rack_api
from app.api.discovery import router as discovery_router
from app.api.ws_discovery import router as ws_discovery_router
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
    # docs.body_html + v0.1.2 sidebar columns
    doc_cols = _get_columns(conn, "docs")
    if "body_html" not in doc_cols:
        conn.execute("ALTER TABLE docs ADD COLUMN body_html TEXT")
    if "category" not in doc_cols:
        conn.execute("ALTER TABLE docs ADD COLUMN category TEXT DEFAULT ''")
    if "pinned" not in doc_cols:
        conn.execute("ALTER TABLE docs ADD COLUMN pinned INTEGER DEFAULT 0")
    if "icon" not in doc_cols:
        conn.execute("ALTER TABLE docs ADD COLUMN icon TEXT DEFAULT ''")
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

    # v0.1.4-discovery: services.slug backfill — discovery-created services may have
    # NULL slugs because the auto-merge path wrote ORM rows directly without setting
    # the slug column (which has a NOT NULL UNIQUE constraint).
    # Derive a slug from the service name + id suffix to guarantee uniqueness.
    slug_rows = conn.execute(
        "SELECT id, name FROM services WHERE slug IS NULL OR slug = ''"
    ).fetchall()
    for svc_id, svc_name in slug_rows:
        if not svc_name:
            svc_name = f"service-{svc_id}"
        base = _re.sub(r'[^a-z0-9]+', '-', svc_name.lower()).strip('-')
        candidate = base
        # Ensure uniqueness against already-committed slugs
        counter = 1
        while conn.execute(
            "SELECT 1 FROM services WHERE slug = ? AND id != ?", (candidate, svc_id)
        ).fetchone():
            candidate = f"{base}-{counter}"
            counter += 1
        conn.execute("UPDATE services SET slug = ? WHERE id = ?", (candidate, svc_id))
    if slug_rows:
        _logger.info("Slug backfill: %d service rows updated", len(slug_rows))

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

    # v0.1.4-discovery: hardware discovery columns
    hw_cols = _get_columns(conn, "hardware")
    if "mac_address" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN mac_address TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "status" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN status TEXT DEFAULT 'unknown'")
    hw_cols = _get_columns(conn, "hardware")
    if "last_seen" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN last_seen TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "discovered_at" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN discovered_at TEXT")
    hw_cols = _get_columns(conn, "hardware")
    if "source" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN source TEXT DEFAULT 'manual'")
    hw_cols = _get_columns(conn, "hardware")
    if "os_version" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN os_version TEXT")

    # v0.1.4-discovery: scan_jobs + scan_results tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER REFERENCES discovery_profiles(id) ON DELETE SET NULL,
            label TEXT,
            target_cidr TEXT NOT NULL,
            scan_types_json TEXT NOT NULL DEFAULT '["nmap"]',
            status TEXT NOT NULL DEFAULT 'queued',
            triggered_by TEXT DEFAULT 'api',
            hosts_found INTEGER DEFAULT 0,
            hosts_new INTEGER DEFAULT 0,
            hosts_updated INTEGER DEFAULT 0,
            hosts_conflict INTEGER DEFAULT 0,
            error_text TEXT,
            progress_phase TEXT,
            progress_message TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_job_id INTEGER NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
            ip_address TEXT NOT NULL,
            mac_address TEXT,
            hostname TEXT,
            open_ports_json TEXT,
            os_family TEXT,
            os_vendor TEXT,
            snmp_sys_name TEXT,
            snmp_sys_descr TEXT,
            raw_nmap_xml TEXT,
            state TEXT NOT NULL DEFAULT 'new',
            merge_status TEXT NOT NULL DEFAULT 'pending',
            matched_entity_type TEXT,
            matched_entity_id INTEGER,
            conflicts_json TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discovery_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cidr TEXT NOT NULL,
            scan_types TEXT NOT NULL DEFAULT '["nmap"]',
            nmap_arguments TEXT,
            snmp_community_encrypted TEXT,
            snmp_version TEXT DEFAULT '2c',
            snmp_port INTEGER DEFAULT 161,
            enabled INTEGER NOT NULL DEFAULT 1,
            schedule TEXT,
            last_run TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # v0.1.4-cortex: racks table + hardware.rack_id, hardware.source_scan_result_id, compute_units.status
    conn.execute("""
        CREATE TABLE IF NOT EXISTS racks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            height_u INTEGER NOT NULL DEFAULT 42,
            location TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','utc')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','utc'))
        )
    """)
    hw_cols = _get_columns(conn, "hardware")
    if "rack_id" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN rack_id INTEGER REFERENCES racks(id)")
    hw_cols = _get_columns(conn, "hardware")
    if "source_scan_result_id" not in hw_cols:
        conn.execute("ALTER TABLE hardware ADD COLUMN source_scan_result_id INTEGER REFERENCES scan_results(id)")
    cu_cols = _get_columns(conn, "compute_units")
    if "status" not in cu_cols:
        conn.execute("ALTER TABLE compute_units ADD COLUMN status TEXT DEFAULT 'unknown'")
    # MAC unique index (partial — only non-NULL values)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_hardware_mac ON hardware(mac_address) WHERE mac_address IS NOT NULL AND mac_address != ''")

    # v0.1.4-discovery: app_settings discovery columns
    settings_cols = _get_columns(conn, "app_settings")
    if "discovery_auto_merge" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN discovery_auto_merge BOOLEAN DEFAULT FALSE")
    if "discovery_nmap_args" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN discovery_nmap_args TEXT DEFAULT '-sV -O --osscan-limit -T4'")
    if "discovery_snmp_community" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN discovery_snmp_community TEXT")
    if "discovery_http_probe" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN discovery_http_probe BOOLEAN DEFAULT TRUE")
    if "discovery_retention_days" not in settings_cols:
        conn.execute("ALTER TABLE app_settings ADD COLUMN discovery_retention_days INTEGER DEFAULT 30")


# ── App startup / lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks."""
    import asyncio
    from app.services import discovery_service

    # ── DB init & migrations ──────────────────────────────────────────────
    if settings.database_url.startswith(_SQLITE_SCHEME):
        db_path = Path(settings.database_url[len(_SQLITE_SCHEME):])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure writable for WAL mode and migrations
        if db_path.exists():
            try:
                db_path.chmod(0o666)
            except Exception:
                pass

    # CRITICAL: Create all tables first
    Base.metadata.create_all(bind=engine)

    if settings.database_url.startswith(_SQLITE_SCHEME):
        import sqlite3
        db_path_str = settings.database_url[len(_SQLITE_SCHEME):]
        # For in-memory DBs, we can't just use a new connect() because it's a DIFFERENT DB
        # But our engine usually handles connection pooling.
        # However, for migrations we use a raw connection.
        with engine.connect() as conn:
            # We must use the connection from the engine to see the tables in memory
            # sqlalchemy's engine.connect() returns a Connection object.
            # We need the underlying DBAPI connection for raw SQL if using it.
            raw_conn = conn.connection
            _run_migrations(raw_conn)
            raw_conn.commit()

    # Backfill log timestamps via ORM session
    db = SessionLocal()
    try:
        _backfill_log_timestamps(db)
    finally:
        db.close()

    # ── Register main event loop for APScheduler WS broadcasts ───────────
    loop = asyncio.get_running_loop()
    discovery_service.set_main_loop(loop)

    # ── APScheduler — scheduled discovery jobs ────────────────────────────
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()

    # Daily purge of old scan results
    scheduler.add_job(
        discovery_service.purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id="purge_old_scan_results",
        replace_existing=True,
    )

    # Load enabled discovery profiles and schedule them
    sched_db = SessionLocal()
    try:
        from app.db.models import DiscoveryProfile
        profiles = sched_db.query(DiscoveryProfile).filter(
            DiscoveryProfile.enabled == True,  # noqa: E712
            DiscoveryProfile.schedule_cron.isnot(None),
            DiscoveryProfile.schedule_cron != "",
        ).all()
        for profile in profiles:
            try:
                if not profile.schedule_cron:
                    continue
                trigger = CronTrigger.from_crontab(profile.schedule_cron)
                scheduler.add_job(
                    discovery_service.run_scan_job_by_profile,
                    trigger=trigger,
                    args=[profile.id],
                    id=f"discovery_profile_{profile.id}",
                    replace_existing=True,
                )
                _logger.info("Scheduled discovery profile %d (%s)", profile.id, profile.name)
            except Exception as exc:
                _logger.warning("Could not schedule profile %d: %s", profile.id, exc)
    finally:
        sched_db.close()

    scheduler.start()
    _logger.info("APScheduler started.")

    yield  # ── app is running ──

    scheduler.shutdown(wait=False)
    _logger.info("APScheduler stopped.")


# ── FastAPI app ────────────────────────────────────────────────────────────

app = FastAPI(
    title="Circuit Breaker",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ───────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# ── Global error handlers ──────────────────────────────────────────────────

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body)[:500] if exc.body else None},
    )


# ── API routers ────────────────────────────────────────────────────────────

_V1 = "/api/v1"

app.include_router(hardware.router,       prefix=f"{_V1}/hardware",          tags=["hardware"])
app.include_router(compute_units.router,  prefix=f"{_V1}/compute-units",     tags=["compute-units"])
app.include_router(services.router,       prefix=f"{_V1}/services",          tags=["services"])
app.include_router(storage.router,        prefix=f"{_V1}/storage",           tags=["storage"])
app.include_router(networks.router,       prefix=f"{_V1}/networks",          tags=["networks"])
app.include_router(misc.router,           prefix=f"{_V1}/misc",              tags=["misc"])
app.include_router(docs.router,           prefix=f"{_V1}/docs",              tags=["docs"])
app.include_router(graph.router,          prefix=f"{_V1}/graph",             tags=["graph"])
app.include_router(search.router,         prefix=f"{_V1}/search",            tags=["search"])
app.include_router(logs.router,           prefix=f"{_V1}/logs",              tags=["logs"])
app.include_router(auth.router,           prefix=f"{_V1}/auth",              tags=["auth"])
app.include_router(clusters.router,       prefix=f"{_V1}/hardware-clusters", tags=["clusters"])
app.include_router(external_nodes.router, prefix=f"{_V1}/external-nodes",    tags=["external-nodes"])
app.include_router(bootstrap.router,      prefix=f"{_V1}/bootstrap",         tags=["bootstrap"])
app.include_router(catalog.router,        prefix=f"{_V1}/catalog",           tags=["catalog"])
app.include_router(telemetry_api.router,  prefix=f"{_V1}/hardware",          tags=["telemetry"])
app.include_router(categories.router,     prefix=f"{_V1}/categories",        tags=["categories"])
app.include_router(environments.router,   prefix=f"{_V1}/environments",      tags=["environments"])
app.include_router(discovery_router,      prefix=f"{_V1}/discovery",         tags=["discovery"])
app.include_router(ws_discovery_router,   prefix=f"{_V1}/discovery",         tags=["discovery-ws"])
app.include_router(ip_check_router,       prefix=f"{_V1}",                   tags=["ip-check"])
app.include_router(settings_router,       prefix=f"{_V1}/settings",          tags=["settings"])
app.include_router(branding_router,       prefix=f"{_V1}/branding",          tags=["branding"])
app.include_router(admin_router,          prefix=f"{_V1}/admin",             tags=["admin"])
app.include_router(security_router,       prefix=f"{_V1}/security",          tags=["security"])
app.include_router(metrics_router,        prefix=f"{_V1}/metrics",           tags=["metrics"])
app.include_router(timezones_router,      prefix=f"{_V1}/timezones",         tags=["timezones"])
app.include_router(rack_api.router,       prefix=f"{_V1}/racks",             tags=["racks"])


# ── Health check ───────────────────────────────────────────────────────────

@app.get(f"{_V1}/health")
async def health():
    return {"status": "ok"}


# ── Static files & SPA fallback ────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent.parent / "static"
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

def _get_frontend_dir() -> Path | None:
    if _FRONTEND_DIST.exists():
        return _FRONTEND_DIST
    if _STATIC_DIR.exists():
        return _STATIC_DIR
    return None


_frontend_dir = _get_frontend_dir()

if _frontend_dir:
    _assets = _frontend_dir / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    _icons = _frontend_dir / "icons"
    if _icons.exists():
        app.mount("/icons", StaticFiles(directory=str(_icons)), name="icons")

    _data_dir = Path("/app/data")
    _uploads_dir = _data_dir / "uploads"
    _user_icons_dir = _data_dir / "user-icons"
    _branding_dir_data = _uploads_dir / "branding"
    if _uploads_dir.exists():
        app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")
    if _user_icons_dir.exists():
        app.mount("/user-icons", StaticFiles(directory=str(_user_icons_dir)), name="user-icons")
    if _branding_dir_data.exists():
        app.mount("/branding", StaticFiles(directory=str(_branding_dir_data)), name="branding")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        # API routes must never fall through to the SPA
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index = _frontend_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return Response(status_code=404)
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return HTMLResponse("<h1>Circuit Breaker API</h1><p>Frontend not built.</p>")



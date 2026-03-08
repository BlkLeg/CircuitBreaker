import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    auth,
    auth_oauth,
    bootstrap,
    catalog,
    categories,
    clusters,
    compute_units,
    docs,
    environments,
    external_nodes,
    graph,
    hardware,
    logs,
    misc,
    networks,
    search,
    services,
    storage,
)
from app.api import rack as rack_api
from app.api import telemetry as telemetry_api
from app.api.admin import router as admin_router
from app.api.admin_db import router as admin_db_router
from app.api.admin_users import router as admin_users_router
from app.api.assets import router as assets_router
from app.api.branding import router as branding_router
from app.api.capabilities import router as capabilities_router
from app.api.cve import router as cve_router
from app.api.discovery import router as discovery_router
from app.api.events import router as events_router
from app.api.ip_check import router as ip_check_router
from app.api.metrics import router as metrics_router
from app.api.monitor import router as monitor_router
from app.api.notifications import router as notifications_router
from app.api.proxmox import router as proxmox_router
from app.api.security_status import router as security_router
from app.api.settings import router as settings_router
from app.api.system import router as system_router
from app.api.timezones import router as timezones_router
from app.api.vault import router as vault_router
from app.api.webhooks import router as webhooks_router
from app.api.ws_discovery import router as ws_discovery_router
from app.api.ws_topology import router as ws_topology_router
from app.core import (
    compat as _compat,  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi import
)
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import limiter
from app.db import models  # noqa: F401 — import to register all model metadata with Base
from app.db.session import SessionLocal
from app.middleware.legacy_token import LegacyTokenMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

_SQLITE_SCHEME = "sqlite:///"
_logger = logging.getLogger(__name__)


def _seed_default_docs(db) -> None:
    """Seed the single shipped default doc on fresh installs.

    Creates one doc from repository root DocsPage.md only when the docs table is empty.
    """
    from app.core.markdown_render import render_markdown
    from app.db.models import Doc, User

    has_users = db.query(User.id).limit(1).first()
    if has_users:
        return

    has_docs = db.query(Doc.id).limit(1).first()
    if has_docs:
        return

    docs_page_path = Path(__file__).resolve().parents[2] / "DocsPage.md"
    if not docs_page_path.exists():
        _logger.warning("Default docs seed file not found at %s", docs_page_path)
        return

    body_md = docs_page_path.read_text(encoding="utf-8").strip()
    if not body_md:
        _logger.warning("Default docs seed file is empty: %s", docs_page_path)
        return

    title = "Welcome to Circuit Breaker"
    first_line = body_md.splitlines()[0].strip()
    if first_line.startswith("#"):
        parsed_title = first_line.lstrip("#").strip()
        if parsed_title:
            title = parsed_title

    db.add(
        Doc(
            title=title,
            body_md=body_md,
            body_html=render_markdown(body_md),
            category="Getting Started",
            pinned=True,
            icon="book-open",
        )
    )
    db.commit()


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
    from datetime import datetime

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
                val = dt.isoformat() if dt.tzinfo else dt.replace(tzinfo=UTC).isoformat()
            except (ValueError, TypeError):
                pass
        db.execute(
            text("UPDATE logs SET created_at_utc = :val WHERE id = :id"),
            {"val": val, "id": log_id},
        )
    db.commit()


def run_alembic_upgrade():
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app.db.session import engine

    # Resolve alembic.ini relative to this file so it works regardless of CWD.
    # main.py lives at <root>/src/app/main.py; alembic.ini is at <root>/alembic.ini.
    _alembic_ini = str(Path(__file__).resolve().parent.parent.parent / "alembic.ini")

    try:
        insp = inspect(engine)
        table_names = set(insp.get_table_names())

        if not table_names or "alembic_version" not in table_names and "users" not in table_names:
            # Completely fresh database: create all tables directly, then stamp.
            # This bypasses the incremental migration scripts (which were written as
            # diffs against the old SQLite schema and would fail on an empty DB).
            from app.db.models import Base

            Base.metadata.create_all(engine)
            alembic_cfg = Config(_alembic_ini)
            command.stamp(alembic_cfg, "head")
            return

        if "users" in table_names and "alembic_version" not in table_names:
            # Old DB with no alembic tracking: stamp to the revision just before
            # 0017 (webhooks/oauth) so upgrade() will run 0017+ and add any
            # missing columns (e.g. registration_open). Stamping to "head" would
            # make upgrade a no-op and leave the schema outdated.
            alembic_cfg = Config(_alembic_ini)
            command.stamp(alembic_cfg, "a3b4c5d6e7fc")  # 0015_proxmox_storage
    except Exception:
        pass

    alembic_cfg = Config(_alembic_ini)
    command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks.

    Migrations are run by start.py before workers spawn; do not run them here
    to avoid concurrent Alembic execution from multiple workers (crashes).
    """
    import asyncio

    from app.core.nats_client import nats_client
    from app.services import discovery_service

    # ── Phase 7: Vault key init ────────────────────────────────────────────
    # Must run before any scheduler job or service that encrypts/decrypts.
    # Fallback chain: env CB_VAULT_KEY → /data/.env → AppSettings.vault_key
    _vault_db = SessionLocal()
    try:
        from app.services import vault_service as _vault_svc
        from app.services.credential_vault import get_vault as _get_vault

        _vault_key = _vault_svc.load_vault_key(_vault_db)
        if _vault_key:
            _get_vault().reinitialize(_vault_key)
            import os as _os

            _os.environ["CB_VAULT_KEY"] = _vault_key
            _logger.info("Vault initialized from: %s", _vault_svc.get_key_source())
        else:
            _logger.warning(
                "CB_VAULT_KEY not found in environment, %s, or database. "
                "Vault is uninitialized — encrypted credentials will be unavailable "
                "until OOBE completes and a vault key is generated.",
                _vault_svc._DATA_ENV_PATH,
            )
    except Exception as _ve:  # noqa: BLE001
        _logger.warning("Vault init failed during startup: %s", _ve)
    finally:
        _vault_db.close()

    # ── NATS message bus ───────────────────────────────────────────────────
    await nats_client.connect()
    _logger.info("NATS initialised (connected=%s)", nats_client.is_connected)

    # ── NATS → WebSocket bridge ────────────────────────────────────────────
    # Subscribe to topology subjects and fan out to topology WS clients.
    # Also subscribe to notification subjects for SSE fan-out (events.py handles
    # its own subscriptions; this bridge feeds the topology WS manager).
    if nats_client.is_connected:
        import json as _json

        from app.api.ws_topology import topology_ws_manager
        from app.core import subjects as _subj

        async def _topo_handler(msg) -> None:
            try:
                data = _json.loads(msg.data.decode())
            except Exception:
                data = {}
            subject = msg.subject
            if subject == _subj.TOPOLOGY_NODE_MOVED:
                event_type = "node_moved"
            elif subject == _subj.TOPOLOGY_CABLE_ADDED:
                event_type = "cable_added"
            elif subject == _subj.TOPOLOGY_CABLE_REMOVED:
                event_type = "cable_removed"
            elif subject == _subj.TOPOLOGY_NODE_STATUS_CHANGED:
                event_type = "node_status_changed"
            else:
                event_type = subject
            await topology_ws_manager.broadcast({"type": event_type, **data})

        for _topo_subject in (
            _subj.TOPOLOGY_NODE_MOVED,
            _subj.TOPOLOGY_CABLE_ADDED,
            _subj.TOPOLOGY_CABLE_REMOVED,
            _subj.TOPOLOGY_NODE_STATUS_CHANGED,
        ):
            await nats_client.subscribe(_topo_subject, _topo_handler)
        _logger.info("NATS → topology WS bridge subscribed.")

    # ── CVE database (separate SQLite file) ───────────────────────────────
    from app.db.cve_session import init_cve_db

    init_cve_db()

    # ── Dev mode: enable verbose logging ──────────────────────────────────
    if settings.dev_mode:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
        _logger.warning("DEV MODE is enabled — SQL logging is verbose. Do NOT use in production.")

    # ── Register main event loop for APScheduler WS broadcasts ───────────
    loop = asyncio.get_running_loop()
    discovery_service.set_main_loop(loop)

    # ── APScheduler — scheduled discovery jobs ────────────────────────────
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()
    from app.core.scheduler import set_scheduler_instance

    # Keep discovery profile reloads/status views pointed at the live runtime scheduler.
    set_scheduler_instance(scheduler)

    # Daily purge of old scan results
    scheduler.add_job(
        discovery_service.purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id="purge_old_scan_results",
        replace_existing=True,
    )

    # Daily purge of old audit log entries based on retention setting
    from app.services.log_purge import purge_old_audit_logs

    scheduler.add_job(
        purge_old_audit_logs,
        trigger=CronTrigger(hour=3, minute=15),
        id="audit_log_purge",
        replace_existing=True,
    )

    # Daily uptime rollup for fast historical uptime reads.
    from app.workers.rollup_worker import run_rollup_job

    scheduler.add_job(
        run_rollup_job,
        trigger=CronTrigger(hour=0, minute=5),
        id="daily_uptime_rollup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Daily PostgreSQL backup (no-op for SQLite installs)
    from app.services.db_backup import backup_postgres

    scheduler.add_job(
        backup_postgres,
        trigger=CronTrigger(hour=3, minute=30),
        id="pg_backup",
        replace_existing=True,
    )

    # CVE sync — only scheduled when enabled in settings
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.cve_service import sync_nvd_feed

    cve_db = SessionLocal()
    try:
        cve_settings = cve_db.query(models.AppSettings).first()
        if cve_settings and cve_settings.cve_sync_enabled:
            interval_hours = cve_settings.cve_sync_interval_hours or 24
            scheduler.add_job(
                sync_nvd_feed,
                trigger=IntervalTrigger(hours=interval_hours),
                id="cve_sync",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            _logger.info("CVE sync scheduled every %d hours", interval_hours)
    finally:
        cve_db.close()

    # IP Pool refresh every hour
    scheduler.add_job(
        discovery_service.refresh_ip_pool,
        trigger=CronTrigger(minute=0),
        id="refresh_ip_pool",
        replace_existing=True,
        max_instances=1,
    )

    # Load enabled discovery profiles and schedule them
    sched_db = SessionLocal()
    try:
        from app.db.models import DiscoveryProfile

        profiles = (
            sched_db.query(DiscoveryProfile)
            .filter(
                DiscoveryProfile.enabled == 1,  # Integer column (0/1), not Boolean
                DiscoveryProfile.schedule_cron.isnot(None),
                DiscoveryProfile.schedule_cron != "",
            )
            .all()
        )
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

    # Uptime monitor — poll all enabled monitors every 30 seconds
    from apscheduler.triggers.interval import IntervalTrigger as _IT

    from app.services.monitor_service import run_all_monitors_job

    _monitor_interval = int(os.environ.get("UPTIME_MONITOR_INTERVAL_S", "30"))
    scheduler.add_job(
        run_all_monitors_job,
        trigger=_IT(seconds=_monitor_interval),
        id="uptime_monitor",
        replace_existing=True,
        max_instances=1,
    )
    _logger.info("Uptime monitor scheduled (%ds interval).", _monitor_interval)

    # Docker topology sync — only when docker_discovery_enabled
    docker_db = SessionLocal()
    try:
        docker_settings = docker_db.query(models.AppSettings).first()
        if docker_settings and getattr(docker_settings, "docker_discovery_enabled", False):
            interval_mins = getattr(docker_settings, "docker_sync_interval_minutes", 5) or 5
            from app.services.docker_discovery import run_docker_sync_job

            scheduler.add_job(
                run_docker_sync_job,
                trigger=_IT(minutes=interval_mins),
                id="docker_topology_sync",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=60,
            )
            _logger.info("Docker topology sync scheduled every %d minutes.", interval_mins)
    finally:
        docker_db.close()

    # ── Proxmox telemetry polling ────────────────────────────────────────
    from app.services.proxmox_service import (
        discover_and_import,
        list_integrations,
        poll_node_telemetry,
        poll_vm_telemetry,
    )

    async def _proxmox_node_poll():
        _pdb = SessionLocal()
        try:
            await poll_node_telemetry(_pdb)
        finally:
            _pdb.close()

    async def _proxmox_vm_poll():
        _pdb = SessionLocal()
        try:
            await poll_vm_telemetry(_pdb)
        finally:
            _pdb.close()

    async def _proxmox_full_sync():
        _pdb = SessionLocal()
        try:
            configs = list_integrations(_pdb)
            for cfg in configs:
                if cfg.auto_sync:
                    try:
                        await discover_and_import(_pdb, cfg)
                    except Exception as exc:
                        _logger.warning("Proxmox full sync failed for %d: %s", cfg.id, exc)
        finally:
            _pdb.close()

    pxmx_db = SessionLocal()
    try:
        from sqlalchemy import func

        from app.db.models import IntegrationConfig

        has_proxmox = (
            pxmx_db.query(IntegrationConfig)
            .filter(
                IntegrationConfig.type == "proxmox",
                IntegrationConfig.auto_sync.is_(True),
            )
            .first()
        )
        if has_proxmox:
            _pxmx_node_s = int(os.environ.get("PROXMOX_NODE_POLL_SECONDS", "30"))
            _pxmx_vm_s = int(os.environ.get("PROXMOX_VM_POLL_SECONDS", "120"))
            scheduler.add_job(
                _proxmox_node_poll,
                trigger=_IT(seconds=_pxmx_node_s),
                id="proxmox_node_telemetry",
                replace_existing=True,
                max_instances=1,
            )
            scheduler.add_job(
                _proxmox_vm_poll,
                trigger=_IT(seconds=_pxmx_vm_s),
                id="proxmox_vm_telemetry",
                replace_existing=True,
                max_instances=1,
            )
            sync_interval = (
                pxmx_db.query(func.min(IntegrationConfig.sync_interval_s))
                .filter(
                    IntegrationConfig.type == "proxmox",
                    IntegrationConfig.auto_sync.is_(True),
                )
                .scalar()
                or 300
            )
            scheduler.add_job(
                _proxmox_full_sync,
                trigger=_IT(seconds=sync_interval),
                id="proxmox_full_sync",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=120,
            )
            _logger.info(
                "Proxmox scheduled: telemetry (nodes 30s, VMs 120s), full sync every %ds.",
                sync_interval,
            )
    finally:
        pxmx_db.close()

    # ── Phase 4: ARP Prober — scheduled subnet sweep ───────────────────────
    phase4_db = SessionLocal()
    try:
        phase4_settings = phase4_db.query(models.AppSettings).first()
        if phase4_settings and getattr(phase4_settings, "arp_enabled", True):
            prober_interval = getattr(phase4_settings, "prober_interval_minutes", 15) or 15
            from app.services.prober_service import run_prober_job

            scheduler.add_job(
                run_prober_job,
                trigger=_IT(minutes=prober_interval),
                id="arp_prober",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=120,
            )
            _logger.info("ARP prober scheduled every %d minutes.", prober_interval)
    finally:
        phase4_db.close()

    scheduler.start()
    _logger.info("APScheduler started.")

    # ── Phase 4: Always-On Listener (mDNS + SSDP) ─────────────────────────
    from app.services.listener_service import listener_service

    listener_db = SessionLocal()
    try:
        listener_settings = listener_db.query(models.AppSettings).first()
        if listener_settings and getattr(listener_settings, "listener_enabled", False):
            asyncio.create_task(listener_service.start(listener_settings))
            _logger.info("Always-on listener started.")
    finally:
        listener_db.close()

    # ── Webhook and notification workers ──────────────────────────────────
    from app.workers import discovery as discovery_worker
    from app.workers import notification_worker, webhook_worker

    asyncio.create_task(webhook_worker.run_worker())
    asyncio.create_task(notification_worker.run_worker())
    asyncio.create_task(discovery_worker.run_worker())
    _logger.info("Webhook, notification, and discovery workers started.")

    yield  # ── app is running ──

    await listener_service.stop()
    scheduler.shutdown(wait=False)
    _logger.info("APScheduler stopped.")

    # ── Graceful NATS disconnect ───────────────────────────────────────────
    await nats_client.disconnect()
    _logger.info("NATS disconnected.")


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
app.add_middleware(LegacyTokenMiddleware)
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


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    if settings.dev_mode:
        import traceback

        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "traceback": traceback.format_exc()},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── API routers ────────────────────────────────────────────────────────────

_V1 = "/api/v1"

app.include_router(hardware.router, prefix=f"{_V1}/hardware", tags=["hardware"])
app.include_router(hardware.hw_conn_router, prefix=f"{_V1}", tags=["hardware"])
app.include_router(compute_units.router, prefix=f"{_V1}/compute-units", tags=["compute-units"])
app.include_router(services.router, prefix=f"{_V1}/services", tags=["services"])
app.include_router(storage.router, prefix=f"{_V1}/storage", tags=["storage"])
app.include_router(networks.router, prefix=f"{_V1}/networks", tags=["networks"])
app.include_router(misc.router, prefix=f"{_V1}/misc", tags=["misc"])
app.include_router(docs.router, prefix=f"{_V1}/docs", tags=["docs"])
app.include_router(graph.router, prefix=f"{_V1}/graph", tags=["graph"])
app.include_router(search.router, prefix=f"{_V1}/search", tags=["search"])
app.include_router(logs.router, prefix=f"{_V1}/logs", tags=["logs"])
app.include_router(auth.auth_jwt_router, prefix=f"{_V1}/auth/jwt", tags=["auth"])
app.include_router(auth.reset_password_router, prefix=f"{_V1}/auth", tags=["auth"])
app.include_router(auth.user_me_router, prefix=f"{_V1}/users", tags=["users"])
app.include_router(auth.users_router, prefix=f"{_V1}/users", tags=["users"])
app.include_router(auth.router, prefix=f"{_V1}/auth", tags=["auth"])
app.include_router(clusters.router, prefix=f"{_V1}/hardware-clusters", tags=["clusters"])
app.include_router(external_nodes.router, prefix=f"{_V1}/external-nodes", tags=["external-nodes"])
app.include_router(bootstrap.router, prefix=f"{_V1}/bootstrap", tags=["bootstrap"])
app.include_router(catalog.router, prefix=f"{_V1}/catalog", tags=["catalog"])
app.include_router(telemetry_api.router, prefix=f"{_V1}/hardware", tags=["telemetry"])
app.include_router(telemetry_api.router, prefix=f"{_V1}/telemetry", tags=["telemetry"])
app.include_router(categories.router, prefix=f"{_V1}/categories", tags=["categories"])
app.include_router(environments.router, prefix=f"{_V1}/environments", tags=["environments"])
app.include_router(discovery_router, prefix=f"{_V1}/discovery", tags=["discovery"])
app.include_router(ws_discovery_router, prefix=f"{_V1}/discovery", tags=["discovery-ws"])
app.include_router(ws_topology_router, prefix=f"{_V1}/topology", tags=["topology-ws"])
app.include_router(ip_check_router, prefix=f"{_V1}", tags=["ip-check"])
app.include_router(settings_router, prefix=f"{_V1}/settings", tags=["settings"])
app.include_router(system_router, prefix=f"{_V1}/system", tags=["system"])
app.include_router(branding_router, prefix=f"{_V1}/branding", tags=["branding"])
app.include_router(assets_router, prefix=f"{_V1}/assets", tags=["assets"])
app.include_router(admin_router, prefix=f"{_V1}/admin", tags=["admin"])
app.include_router(admin_users_router, prefix=f"{_V1}", tags=["admin-users"])
app.include_router(admin_db_router, prefix=f"{_V1}/admin", tags=["admin-db"])
app.include_router(security_router, prefix=f"{_V1}/security", tags=["security"])
app.include_router(vault_router, prefix=f"{_V1}", tags=["vault"])
app.include_router(metrics_router, prefix=f"{_V1}/metrics", tags=["metrics"])
app.include_router(timezones_router, prefix=f"{_V1}/timezones", tags=["timezones"])
app.include_router(rack_api.router, prefix=f"{_V1}/racks", tags=["racks"])

app.include_router(capabilities_router, prefix=f"{_V1}/capabilities", tags=["capabilities"])
app.include_router(cve_router, prefix=f"{_V1}/cve", tags=["cve"])
app.include_router(monitor_router, prefix=f"{_V1}/monitors", tags=["monitors"])
app.include_router(events_router, prefix=f"{_V1}/events", tags=["events"])
app.include_router(webhooks_router, prefix=f"{_V1}/webhooks", tags=["webhooks"])
app.include_router(notifications_router, prefix=f"{_V1}/notifications", tags=["notifications"])
app.include_router(auth_oauth.router, prefix=f"{_V1}", tags=["oauth"])
app.include_router(proxmox_router, prefix=f"{_V1}/integrations/proxmox", tags=["proxmox"])


# ── Health check ───────────────────────────────────────────────────────────


@app.api_route(f"{_V1}/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}


# ── Static files & SPA fallback ────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent.parent / "static"
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def _get_frontend_dir() -> Path | None:
    # Prefer settings.static_dir which maps to the STATIC_DIR env var.
    # The Dockerfile sets STATIC_DIR=/app/frontend/dist; the default "../frontend/dist"
    # is resolved relative to the backend working directory (/app/backend in Docker).
    sd = Path(settings.static_dir)
    if not sd.is_absolute():
        sd = Path.cwd() / sd
    if sd.exists():
        return sd
    # Legacy fallbacks for local dev layouts
    if _FRONTEND_DIST.exists():
        return _FRONTEND_DIST
    if _STATIC_DIR.exists():
        return _STATIC_DIR
    return None


_frontend_dir = _get_frontend_dir()
_frontend_root_files: dict[str, Path] = {}
if _frontend_dir:
    _frontend_dir_resolved = _frontend_dir.resolve()
    for _entry in _frontend_dir_resolved.iterdir():
        if _entry.is_file():
            _frontend_root_files[_entry.name] = _entry

_uploads_dir = Path(settings.uploads_dir)
_user_icons_dir = _uploads_dir / "icons"
_branding_dir_data = _uploads_dir / "branding"

# Ensure directories exist so mounting never fails
_uploads_dir.mkdir(parents=True, exist_ok=True)
_user_icons_dir.mkdir(parents=True, exist_ok=True)
_branding_dir_data.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")
app.mount("/user-icons", StaticFiles(directory=str(_user_icons_dir)), name="user-icons")
app.mount("/branding", StaticFiles(directory=str(_branding_dir_data)), name="branding")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_file():
    favicon = _branding_dir_data / "favicon.ico"
    if favicon.exists():
        return FileResponse(str(favicon), media_type="image/x-icon")
    if _frontend_dir and (_frontend_dir / "favicon.ico").exists():
        return FileResponse(str(_frontend_dir / "favicon.ico"), media_type="image/x-icon")
    return Response(status_code=404)


if _frontend_dir:
    _assets = _frontend_dir / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    _icons = _frontend_dir / "icons"
    if _icons.exists():
        app.mount("/icons", StaticFiles(directory=str(_icons)), name="icons")

    @app.get(
        "/{full_path:path}", include_in_schema=False, responses={404: {"description": "Not found"}}
    )
    async def spa_fallback(full_path: str, request: Request):
        # API routes must never fall through to the SPA
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        # Serve real files from the dist directory (e.g. site.webmanifest, PWA
        # icons) before falling back to the SPA index.html.  Without this check,
        # the browser receives HTML when it requests JSON/binary assets and shows
        # "Manifest: Syntax error" or broken icon errors.
        frontend_dir_resolved = _frontend_dir.resolve()  # type: ignore[operator]
        rel_path = PurePosixPath(full_path.lstrip("/"))
        if any(part in (".", "..") for part in rel_path.parts):
            raise HTTPException(status_code=404, detail="Not found")
        if len(rel_path.parts) == 1:
            candidate = _frontend_root_files.get(rel_path.parts[0])
        else:
            candidate = None
        if candidate and candidate.is_file():
            content_type, _ = mimetypes.guess_type(candidate.name)
            return Response(content=candidate.read_bytes(), media_type=content_type)
        index = frontend_dir_resolved / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return Response(status_code=404)
else:

    @app.get("/", include_in_schema=False)
    async def root():
        return HTMLResponse("<h1>Circuit Breaker API</h1><p>Frontend not built.</p>")

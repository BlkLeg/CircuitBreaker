import logging
import mimetypes
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta  # noqa: F401 — used by models imported transitively
from pathlib import Path, PurePosixPath

import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

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
from app.api import (
    tags as tags_api,
)
from app.api import telemetry as telemetry_api
from app.api.admin import router as admin_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_db import router as admin_db_router
from app.api.admin_users import router as admin_users_router
from app.api.assets import router as assets_router
from app.api.branding import router as branding_router
from app.api.capabilities import router as capabilities_router
from app.api.certificates import router as certificates_router
from app.api.cve import router as cve_router
from app.api.discovery import router as discovery_router
from app.api.events import router as events_router
from app.api.integration_provider import router as integration_provider_router
from app.api.ip_check import router as ip_check_router
from app.api.ipam import ipam_router, node_relations_router, site_router, vlan_router
from app.api.metrics import router as metrics_router
from app.api.monitor import router as monitor_router
from app.api.notifications import router as notifications_router
from app.api.proxmox import router as proxmox_router
from app.api.security_status import router as security_router
from app.api.settings import router as settings_router
from app.api.status import router as status_router
from app.api.system import router as system_router
from app.api.timezones import router as timezones_router
from app.api.topologies import router as topologies_router
from app.api.vault import router as vault_router
from app.api.webhooks import router as webhooks_router
from app.api.ws_discovery import router as ws_discovery_router
from app.api.ws_status import router as ws_status_router
from app.api.ws_status import set_status_main_loop
from app.api.ws_telemetry import router as ws_telemetry_router
from app.api.ws_topology import router as ws_topology_router
from app.core import (
    compat as _compat,  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi import
)
from app.core.config import settings
from app.core.errors import AppError
from app.core.log_redaction import install_global_log_redaction
from app.core.rate_limit import limiter
from app.core.security import _log_api_token_deprecation, require_auth
from app.core.sql_hardening import build_audit_partition_sql
from app.core.time import utcnow
from app.db import models  # noqa: F401 — import to register all model metadata with Base
from app.db.async_session import AsyncSessionLocal
from app.db.session import engine, get_session_context
from app.middleware.csrf import CSRFMiddleware
from app.middleware.legacy_token import LegacyTokenMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant_middleware import TenantMiddleware

# ---------------------------------------------------------------------------
# OAuth param scrubber for uvicorn access logs
# ---------------------------------------------------------------------------
# The OAuth callback URLs carry one-time-use `code` and `state` query params
# that are sensitive — logging them verbatim would allow replaying the flow
# from log files.  This filter replaces their values with [redacted] in
# uvicorn's access log before anything is written to disk.
_OAUTH_SCRUB_RE = re.compile(
    r"(?<=[?&])(?:code|state|oauth_token|access_token)=[^& \"]+",
    re.IGNORECASE,
)


class _OAuthScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            record.args = tuple(
                _OAUTH_SCRUB_RE.sub(lambda m: m.group(0).split("=")[0] + "=[redacted]", a)
                if isinstance(a, str)
                else a
                for a in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(_OAuthScrubFilter())
install_global_log_redaction()

_DOCS_SEED_FILENAME = "DocsPage.md"
_ALEMBIC_INI_FILENAME = "alembic.ini"
_FAVICON_FILENAME = "favicon.ico"
_logger = logging.getLogger(__name__)
SERVER_START_TIME = time.time()


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

    _p = Path(__file__).resolve()
    _docs_candidates: list[str | Path | None] = [
        os.environ.get("CB_DOCS_SEED_FILE"),
        _share_dir_candidate(_DOCS_SEED_FILENAME),
        _bundle_share_candidate(_DOCS_SEED_FILENAME),
        _meipass_candidate(_DOCS_SEED_FILENAME),
        _p.parents[2] / _DOCS_SEED_FILENAME if len(_p.parents) > 2 else None,
    ]
    if len(_p.parents) > 4:
        _docs_candidates.append(_p.parents[4] / _DOCS_SEED_FILENAME)
    docs_page_path = _resolve_existing_path(*_docs_candidates)
    if docs_page_path is None:
        _logger.warning("Default docs seed file not found in configured resource paths")
        return
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
    """Return the column names for a table (PostgreSQL version)."""
    from sqlalchemy import text  # local import — text only needed here

    result = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return [r[0] for r in result]


def run_alembic_upgrade():
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app.db.session import engine

    # Resolve alembic.ini relative to this file so it works regardless of CWD.
    # Mono/backend Docker: main.py at /app/backend/src/app/main.py,
    # alembic.ini at /app/backend/alembic.ini.
    # Repo: main.py at <root>/apps/backend/src/app/main.py,
    # alembic.ini at <root>/apps/backend/alembic.ini.
    _p = Path(__file__).resolve()
    _alembic_candidates: list[str | Path | None] = [
        os.environ.get("ALEMBIC_CONFIG"),
        os.environ.get("CB_ALEMBIC_INI"),
        _share_dir_candidate("backend", _ALEMBIC_INI_FILENAME),
        _bundle_share_candidate("backend", _ALEMBIC_INI_FILENAME),
        _meipass_candidate("backend", _ALEMBIC_INI_FILENAME),
        _p.parent.parent.parent / _ALEMBIC_INI_FILENAME,
    ]
    if len(_p.parents) > 4:
        _alembic_candidates.append(_p.parents[4] / "apps" / "backend" / _ALEMBIC_INI_FILENAME)
    alembic_ini_path = _resolve_existing_path(*_alembic_candidates)
    if alembic_ini_path is None:
        raise FileNotFoundError("Could not locate alembic.ini for migrations")
    _alembic_ini = str(alembic_ini_path)

    try:
        insp = inspect(engine)
        table_names = set(insp.get_table_names())

        if "users" in table_names and "alembic_version" not in table_names:
            # Old DB with no alembic tracking: stamp to the revision just before
            # 0017 (webhooks/oauth) so upgrade() will run 0017+ and add any
            # missing columns (e.g. registration_open). Stamping to "head" would
            # make upgrade a no-op and leave the schema outdated.
            alembic_cfg = Config(_alembic_ini)
            command.stamp(alembic_cfg, "a3b4c5d6e7fc")  # 0015_proxmox_storage
    except Exception as e:
        logging.exception("Migration pre-check failed: %s", e)
        raise

    alembic_cfg = Config(_alembic_ini)
    command.upgrade(alembic_cfg, "head")


def _assert_required_schema() -> None:
    from sqlalchemy import inspect

    from app.db.session import engine

    try:
        existing_tables = set(inspect(engine).get_table_names())
    except Exception as exc:  # noqa: BLE001
        _logger.critical("Database schema check failed before startup: %s", exc, exc_info=True)
        raise SystemExit(1) from exc

    required_tables = {"app_settings", "status_pages", "webhook_rules"}
    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        _logger.critical(
            "Database schema is missing required tables (%s). "
            "Alembic migrations did not run successfully.",
            ", ".join(missing_tables),
        )
        raise SystemExit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks.

    Migrations run here when CB_AUTO_MIGRATE=true (default) or when no external
    entrypoint has already applied them.  In multi-worker production deployments
    the Docker entrypoint calls run_alembic_upgrade() before spawning workers to
    avoid concurrent DDL; the guard here is a safe fallback for bare uvicorn / dev.
    """
    import asyncio
    import concurrent.futures

    asyncio.get_event_loop().set_default_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=32)
    )

    from app.core.nats_client import nats_client
    from app.core.server_state import ServerState, set_state
    from app.services import discovery_service

    set_state(ServerState.STARTING)
    _logger.info("[lifecycle] server state → STARTING")

    # Emit one-shot deprecation warning if CB_API_TOKEN is still set in the environment
    _log_api_token_deprecation()

    # ── Phase 1: Filesystem write validation ───────────────────────────────
    # Fail fast if /data volume permissions are broken (avoids cryptic runtime errors).
    _data_dir = Path(os.environ.get("CB_DATA_DIR", "/data"))
    _test_paths = [
        _data_dir,
        _data_dir / "uploads",
        Path(settings.uploads_dir) if not settings.uploads_dir.startswith("/data") else None,
    ]
    for _path in filter(None, _test_paths):
        try:
            _path.mkdir(parents=True, exist_ok=True)
            _test_file = _path / ".write_test"
            _test_file.touch()
            _test_file.unlink()
        except (PermissionError, OSError) as _pe:
            _logger.critical(
                "STARTUP FAILED: Cannot write to %s. Volume permissions are incorrect. "
                "Fix: docker run --rm -v circuitbreaker-data:/data alpine "
                "sh -c 'chown -R 1000:1000 /data'",
                _path,
            )
            raise SystemExit(1) from _pe
    _logger.info("Filesystem validation passed — data dir: %s", _data_dir)

    # ── Phase 1b: Auto-migrate ─────────────────────────────────────────────
    # Run pending Alembic migrations before any schema check.  Safe for both
    # single-worker dev (make dev) and multi-worker prod: if another worker
    # already applied the migrations the upgrade call is an instant no-op.
    # Set CB_AUTO_MIGRATE=false to disable (e.g. when entrypoint pre-migrates).
    if os.environ.get("CB_AUTO_MIGRATE", "true").lower() != "false":
        try:
            run_alembic_upgrade()
            _logger.info("Alembic migrations applied (or already at head).")
        except Exception as _me:  # noqa: BLE001
            _logger.warning(
                "Auto-migrate failed (schema may be stale): %s — "
                "run 'make migrate' or 'alembic upgrade head' manually.",
                _me,
            )

    _assert_required_schema()

    # ── Phase 1c: Auto-detect api_base_url ────────────────────────────────
    # On native installs api_base_url is often null, causing invite emails to
    # embed the backend URL (localhost:8000) instead of the frontend URL.
    # If unset, detect the LAN IP and default to http://<ip>:8088 (native port).
    def _detect_lan_ip() -> str | None:
        import socket as _socket

        try:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as _s:
                _s.connect(("8.8.8.8", 80))
                return _s.getsockname()[0]
        except Exception:
            return None

    try:
        with get_session_context() as _url_db:
            from app.services.settings_service import get_or_create_settings as _get_settings

            _url_cfg = _get_settings(_url_db)
            if not _url_cfg.api_base_url:
                _lan_ip = _detect_lan_ip()
                if _lan_ip and not _lan_ip.startswith("127."):
                    _url_cfg.api_base_url = f"http://{_lan_ip}:8088"
                    _url_db.commit()
                    _logger.info("Auto-set api_base_url to %s", _url_cfg.api_base_url)
    except Exception as _url_exc:
        _logger.debug("api_base_url auto-detect skipped: %s", _url_exc)

    # ── Phase 7: Vault key init ────────────────────────────────────────────
    # Must run before any scheduler job or service that encrypts/decrypts.
    # Fallback chain: env CB_VAULT_KEY → /data/.env → AppSettings.vault_key
    try:
        with get_session_context() as _vault_db:
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
        _logger.critical("Vault init failed during startup: %s", _ve, exc_info=True)
        raise SystemExit(1) from _ve

    # ── Status page default seed ───────────────────────────────────────────
    with get_session_context() as _status_db:
        try:
            from app.services.status_page_service import get_or_create_default_page

            get_or_create_default_page(_status_db)
        except Exception as _se:  # noqa: BLE001
            _logger.debug("Status page seed skipped or failed: %s", _se)

    # ── Redis (telemetry cache + pub/sub) ────────────────────────────────
    from app.core.redis import close_redis, init_redis

    await init_redis(settings.redis_url)

    # ── NATS message bus ───────────────────────────────────────────────────
    await nats_client.connect()
    _logger.info("NATS initialised (connected=%s)", nats_client.is_connected)

    # ── NATS → WebSocket bridge ────────────────────────────────────────────
    # Subscribe to topology subjects and fan out to topology WS clients.
    # Also subscribe to notification subjects for SSE fan-out (events.py handles
    # its own subscriptions; this bridge feeds the topology WS manager).
    _lifespan_subs: list = []  # track for explicit unsubscribe on shutdown
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
            _sub = await nats_client.subscribe(_topo_subject, _topo_handler)
            if _sub:
                _lifespan_subs.append(_sub)
        _logger.info("NATS → topology WS bridge subscribed.")

        # ── NATS → discovery WebSocket bridge ─────────────────────────────
        # Forwards ALL discovery events (both Proxmox and regular network
        # scans) to discovery WS clients.  This is a secondary delivery
        # path — Redis pub/sub is the primary cross-worker mechanism for
        # regular scans.  Proxmox events that arrive via NATS are mapped
        # to their specific WS message types; regular discovery events are
        # forwarded using their embedded ``event_type``.
        from app.core.ws_manager import ws_manager

        async def _discovery_scan_handler(msg) -> None:
            try:
                data = _json.loads(msg.data.decode())
            except Exception:
                data = {}
            subject = msg.subject

            if data.get("source") == "proxmox":
                if subject == _subj.DISCOVERY_SCAN_STARTED:
                    await ws_manager.broadcast(
                        {
                            "type": "proxmox_scan_started",
                            "integration_id": data.get("integration_id"),
                        }
                    )
                elif subject == _subj.DISCOVERY_SCAN_PROGRESS:
                    await ws_manager.broadcast(
                        {
                            "type": "proxmox_scan_progress",
                            "integration_id": data.get("integration_id"),
                            "phase": data.get("phase"),
                            "message": data.get("message"),
                            "percent": data.get("percent"),
                        }
                    )
                elif subject == _subj.DISCOVERY_SCAN_COMPLETED:
                    await ws_manager.broadcast(
                        {
                            "type": "proxmox_scan_completed",
                            "integration_id": data.get("integration_id"),
                            "nodes": data.get("nodes"),
                            "vms": data.get("vms"),
                            "cts": data.get("cts"),
                            "storage": data.get("storage"),
                        }
                    )
                elif subject == _subj.DISCOVERY_SCAN_FAILED:
                    await ws_manager.broadcast(
                        {
                            "type": "proxmox_scan_failed",
                            "integration_id": data.get("integration_id"),
                            "error": data.get("error"),
                        }
                    )
            else:
                event_type = data.pop("event_type", None)
                if event_type:
                    await ws_manager.broadcast({"type": event_type, **data})

        for _disc_subject in (
            _subj.DISCOVERY_SCAN_STARTED,
            _subj.DISCOVERY_SCAN_PROGRESS,
            _subj.DISCOVERY_SCAN_COMPLETED,
            _subj.DISCOVERY_SCAN_FAILED,
            _subj.DISCOVERY_DEVICE_FOUND,
        ):
            _sub = await nats_client.subscribe(_disc_subject, _discovery_scan_handler)
            if _sub:
                _lifespan_subs.append(_sub)
        _logger.info("NATS → discovery WS bridge subscribed.")

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
    set_status_main_loop(loop)

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

    def _purge_hardware_live_metrics() -> None:
        from app.services.telemetry_service import purge_old_hardware_live_metrics

        with get_session_context() as _tdb:
            removed = purge_old_hardware_live_metrics(_tdb, days=7)
            if removed:
                _logger.info("Purged %d rows from hardware_live_metrics.", removed)
                from app.core.worker_audit import log_worker_audit

                log_worker_audit(
                    action="purge_live_metrics",
                    entity_type="hardware_live_metrics",
                    details=f"purged={removed} retention_days=7",
                    worker_name="scheduler",
                )

    scheduler.add_job(
        _purge_hardware_live_metrics,
        trigger=CronTrigger(hour=3, minute=5),
        id="purge_hardware_live_metrics",
        replace_existing=True,
    )

    # Daily purge of old telemetry_timeseries rows — unbounded table, grows fast
    def _purge_telemetry_timeseries() -> None:
        with get_session_context() as _tdb:
            from sqlalchemy import text as _text

            from app.db.models import AppSettings as _AS

            cfg = _tdb.query(_AS).first()
            retention_days = getattr(cfg, "telemetry_retention_days", None) or 30
            result = _tdb.execute(
                _text(
                    "DELETE FROM telemetry_timeseries WHERE ts < NOW() - (:days * INTERVAL '1 day')"
                ),
                {"days": retention_days},
            )
            removed = result.rowcount
            if removed:
                _logger.info(
                    "Purged %d rows from telemetry_timeseries (retention=%dd).",
                    removed,
                    retention_days,
                )
                from app.core.worker_audit import log_worker_audit

                log_worker_audit(
                    action="purge_telemetry_timeseries",
                    entity_type="telemetry_timeseries",
                    details=f"purged={removed} retention_days={retention_days}",
                    worker_name="scheduler",
                )

    scheduler.add_job(
        _purge_telemetry_timeseries,
        trigger=CronTrigger(hour=3, minute=20),
        id="purge_telemetry_timeseries",
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

    # Monthly audit_log partition maintenance — ensures partitions exist ahead of time
    def _ensure_audit_partitions() -> None:
        try:
            with get_session_context() as db:
                now = utcnow()
                for offset in range(3):
                    dt = now + timedelta(days=30 * offset)
                    db.execute(sa.text(build_audit_partition_sql(dt)))
                db.commit()
        except Exception:
            _logger.debug("audit partition maintenance skipped (table may not exist yet)")

    scheduler.add_job(
        _ensure_audit_partitions,
        trigger=CronTrigger(day=28, hour=2, minute=0),
        id="audit_partition_maintenance",
        replace_existing=True,
    )

    # Disable expired demo accounts (M-18: demo user expiration enforcement)
    def _disable_expired_demo_users() -> None:
        from app.core.time import utcnow
        from app.db.models import User

        try:
            with get_session_context() as db:
                now = utcnow()
                expired = (
                    db.query(User)
                    .filter(
                        User.role == "demo",
                        User.demo_expires.isnot(None),
                        User.demo_expires <= now,
                        User.is_active.is_(True),
                    )
                    .all()
                )
                for u in expired:
                    u.is_active = False
                if expired:
                    db.commit()
                    _logger.info("Disabled %d expired demo user(s)", len(expired))
                    from app.core.worker_audit import log_worker_audit

                    for u in expired:
                        log_worker_audit(
                            action="disable_expired_demo_user",
                            entity_type="user",
                            entity_id=u.id,
                            severity="warn",
                            details=f"email={u.email} demo_expires={u.demo_expires}",
                            worker_name="scheduler",
                        )
        except Exception as exc:
            _logger.warning("Expired demo user cleanup failed: %s", exc)

    scheduler.add_job(
        _disable_expired_demo_users,
        trigger=CronTrigger(hour=4, minute=0),
        id="disable_expired_demo_users",
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

    with get_session_context() as cve_db:
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

    # IP Pool refresh every hour
    scheduler.add_job(
        discovery_service.refresh_ip_pool,
        trigger=CronTrigger(minute=0),
        id="refresh_ip_pool",
        replace_existing=True,
        max_instances=1,
    )

    # Load enabled discovery profiles and schedule them
    with get_session_context() as sched_db:
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

    # Status page polling — every 60s
    from app.workers.status_worker import run_status_poll_job

    scheduler.add_job(
        run_status_poll_job,
        trigger=_IT(minutes=1),
        id="status_page_poll",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    _logger.info("Status page poll scheduled (60s interval).")

    # Docker topology sync — only when docker_discovery_enabled
    with get_session_context() as docker_db:
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

    # ── Proxmox telemetry polling ────────────────────────────────────────
    from app.services.proxmox_service import (
        discover_and_import,
        list_integrations,
        poll_node_telemetry,
        poll_rrd_telemetry,
        poll_vm_telemetry,
        refresh_proxmox_storage,
    )

    async def _proxmox_node_poll():
        try:
            async with asyncio.timeout(25):
                async with AsyncSessionLocal() as _pdb:
                    await poll_node_telemetry(_pdb)
        except TimeoutError:
            _logger.warning("proxmox_node_poll timed out (25s) — skipping cycle")

    async def _proxmox_vm_poll():
        try:
            async with asyncio.timeout(100):
                async with AsyncSessionLocal() as _pdb:
                    await poll_vm_telemetry(_pdb)
        except TimeoutError:
            _logger.warning("proxmox_vm_poll timed out (100s) — skipping cycle")

    async def _proxmox_full_sync():
        try:
            async with asyncio.timeout(270):
                with get_session_context() as _pdb:
                    configs = list_integrations(_pdb)
                    for cfg in configs:
                        if cfg.auto_sync:
                            try:
                                await discover_and_import(_pdb, cfg, queue_for_review=False)
                            except Exception as exc:
                                _logger.warning("Proxmox full sync failed for %d: %s", cfg.id, exc)
        except TimeoutError:
            _logger.warning("proxmox_full_sync timed out (270s) — skipping cycle")

    with get_session_context() as pxmx_db:
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
                coalesce=True,
                misfire_grace_time=15,
            )
            scheduler.add_job(
                _proxmox_vm_poll,
                trigger=_IT(seconds=_pxmx_vm_s),
                id="proxmox_vm_telemetry",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
            _pxmx_rrd_s = int(os.environ.get("PROXMOX_RRD_POLL_SECONDS", "300"))

            async def _proxmox_rrd_poll():
                try:
                    async with asyncio.timeout(270):
                        async with AsyncSessionLocal() as _pdb:
                            await poll_rrd_telemetry(_pdb)
                except TimeoutError:
                    _logger.warning("proxmox_rrd_poll timed out (270s) — skipping cycle")

            scheduler.add_job(
                _proxmox_rrd_poll,
                trigger=_IT(seconds=_pxmx_rrd_s),
                id="proxmox_rrd_telemetry",
                replace_existing=True,
                max_instances=1,
            )

            async def _proxmox_storage_refresh():
                try:
                    async with asyncio.timeout(270):
                        async with AsyncSessionLocal() as _pdb:
                            await refresh_proxmox_storage(_pdb)
                except TimeoutError:
                    _logger.warning("proxmox_storage_refresh timed out (270s) — skipping cycle")

            scheduler.add_job(
                _proxmox_storage_refresh,
                trigger=_IT(seconds=300),
                id="proxmox_storage_refresh",
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
                "Proxmox scheduled: telemetry (nodes 30s, VMs 120s, RRD %ds), full sync every %ds.",
                _pxmx_rrd_s,
                sync_interval,
            )

    # ── Phase 4: ARP Prober — scheduled subnet sweep ───────────────────────
    with get_session_context() as phase4_db:
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

    # ── Certificate auto-renewal (daily at 3:45 AM) ─────────────────────
    def _cert_renewal_job():
        from app.services.certificate_service import check_and_renew_expiring

        with get_session_context() as cert_db:
            check_and_renew_expiring(cert_db)

    scheduler.add_job(
        _cert_renewal_job,
        trigger=CronTrigger(hour=3, minute=45),
        id="cert_auto_renewal",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Vault key auto-rotation (daily at 4:30 AM) ────────────────────
    def _vault_rotation_check():
        from app.services.vault_service import rotate_vault_key

        with get_session_context() as vault_db:
            from app.db.models import AppSettings

            cfg = vault_db.get(AppSettings, 1)
            if not cfg:
                return
            rotation_days = getattr(cfg, "vault_key_rotation_days", 90) or 90
            rotated_at = getattr(cfg, "vault_key_rotated_at", None)
            if rotated_at is None or (utcnow() - rotated_at) > timedelta(days=rotation_days):
                _logger.info(
                    "Vault key rotation due (last rotated: %s, interval: %d days)",
                    rotated_at,
                    rotation_days,
                )
                try:
                    rotate_vault_key(vault_db)
                    from app.core.worker_audit import log_worker_audit

                    log_worker_audit(
                        action="vault_key_rotated",
                        entity_type="vault",
                        severity="warn",
                        details=f"rotation_days={rotation_days}",
                        worker_name="scheduler",
                    )
                except Exception as exc:
                    _logger.error("Vault key auto-rotation failed: %s", exc)

    scheduler.add_job(
        _vault_rotation_check,
        trigger=CronTrigger(hour=4, minute=30),
        id="vault_rotation_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    scheduler.start()
    _logger.info("APScheduler started.")

    # ── Phase 4: Always-On Listener (mDNS + SSDP) ─────────────────────────
    from app.services.listener_service import listener_service

    with get_session_context() as listener_db:
        listener_settings = listener_db.query(models.AppSettings).first()
        if listener_settings and getattr(listener_settings, "listener_enabled", False):
            asyncio.create_task(listener_service.start(listener_settings))
            _logger.info("Always-on listener started.")

    # ── Webhook and notification workers (skip when running with dedicated worker
    # containers, e.g. Docker Compose) ───────────────────────────────────────────
    _run_inprocess_workers = os.environ.get("CB_RUN_INPROCESS_WORKERS", "true").lower() == "true"
    _worker_tasks: list = []
    if _run_inprocess_workers:
        from app.workers import discovery as discovery_worker
        from app.workers import notification_worker, webhook_worker

        _worker_tasks.append(asyncio.create_task(webhook_worker.run_worker()))
        _worker_tasks.append(asyncio.create_task(notification_worker.run_worker()))
        _worker_tasks.append(asyncio.create_task(discovery_worker.run_worker()))
        _logger.info("Webhook, notification, and discovery workers started (in-process).")
    else:
        _logger.info(
            "CB_RUN_INPROCESS_WORKERS=false — webhook/notification/discovery workers "
            "must run as separate containers."
        )

    # ── Phase 9: Update check (non-blocking) ────────────────────────────
    try:
        from app.core.update_check import log_update_notice

        asyncio.create_task(log_update_notice(settings.app_version))
    except Exception:
        pass  # Never let update check affect startup

    set_state(ServerState.READY)
    _logger.info("[lifecycle] server state → READY")

    yield  # ── app is running ──

    set_state(ServerState.STOPPING)
    _logger.info("[lifecycle] server state → STOPPING")

    await listener_service.stop()

    async def shutdown_scheduler():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: scheduler.shutdown(wait=True))

    try:
        await asyncio.wait_for(shutdown_scheduler(), timeout=10.0)
        _logger.info("Scheduler shutdown complete")
    except TimeoutError:
        _logger.warning("Scheduler shutdown timed out after 10s — forcing stop")
        scheduler.shutdown(wait=False)

    # ── Cancel in-process worker tasks ────────────────────────────────────
    for _wt in _worker_tasks:
        _wt.cancel()
    if _worker_tasks:
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
        _logger.info("In-process workers stopped.")

    # ── Unsubscribe NATS lifespan subscriptions ────────────────────────────
    for _ls in _lifespan_subs:
        try:
            await _ls.unsubscribe()
        except Exception:
            pass

    # ── Graceful NATS disconnect ───────────────────────────────────────────
    await nats_client.disconnect()
    _logger.info("NATS disconnected.")

    # ── Graceful Redis disconnect ──────────────────────────────────────────
    await close_redis()


# ── FastAPI app ────────────────────────────────────────────────────────────

app = FastAPI(
    title="Circuit Breaker",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ───────────────────────────────────────────────────────────────────
# Default to same-origin only; never allow wildcard origins in production.
_cors_origins = settings.cors_origins
if not _cors_origins or _cors_origins == ["*"]:
    _cors_origins = []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)
app.add_middleware(CSRFMiddleware)
app.add_middleware(LegacyTokenMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TenantMiddleware)

# ── Global error handlers ──────────────────────────────────────────────────


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.message, "error_code": exc.error_code}
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": jsonable_encoder(exc.errors()),
            "body": str(exc.body)[:500] if exc.body else None,
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    from app.schemas.errors import ErrorCodes

    if settings.dev_mode:
        import traceback

        return JSONResponse(
            status_code=500,
            content={
                "error_code": ErrorCodes.INTERNAL_SERVER_ERROR,
                "detail": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": ErrorCodes.INTERNAL_SERVER_ERROR,
            "detail": "Internal server error",
        },
    )


# ── API routers ────────────────────────────────────────────────────────────

_V1 = "/api/v1"

app.include_router(
    hardware.router,
    prefix=f"{_V1}/hardware",
    tags=["hardware"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    hardware.hw_conn_router,
    prefix=f"{_V1}",
    tags=["hardware"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    compute_units.router,
    prefix=f"{_V1}/compute-units",
    tags=["compute-units"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    services.router,
    prefix=f"{_V1}/services",
    tags=["services"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    storage.router,
    prefix=f"{_V1}/storage",
    tags=["storage"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    networks.router,
    prefix=f"{_V1}/networks",
    tags=["networks"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    misc.router,
    prefix=f"{_V1}/misc",
    tags=["misc"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    docs.router,
    prefix=f"{_V1}/docs",
    tags=["docs"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    graph.router,
    prefix=f"{_V1}/graph",
    tags=["graph"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    search.router,
    prefix=f"{_V1}/search",
    tags=["search"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    logs.router,
    prefix=f"{_V1}/logs",
    tags=["logs"],
    dependencies=[Depends(require_auth)],
)
app.include_router(auth.auth_jwt_router, prefix=f"{_V1}/auth/jwt", tags=["auth"])
app.include_router(
    auth.user_me_router,
    prefix=f"{_V1}/users",
    tags=["users"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    auth.users_router,
    prefix=f"{_V1}/users",
    tags=["users"],
    dependencies=[Depends(require_auth)],
)
app.include_router(auth.router, prefix=f"{_V1}/auth", tags=["auth"])
app.include_router(
    clusters.router,
    prefix=f"{_V1}/hardware-clusters",
    tags=["clusters"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    external_nodes.router,
    prefix=f"{_V1}/external-nodes",
    tags=["external-nodes"],
    dependencies=[Depends(require_auth)],
)
app.include_router(bootstrap.router, prefix=f"{_V1}/bootstrap", tags=["bootstrap"])
app.include_router(
    catalog.router,
    prefix=f"{_V1}/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    telemetry_api.router,
    prefix=f"{_V1}/hardware",
    tags=["telemetry"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    telemetry_api.router,
    prefix=f"{_V1}/telemetry",
    tags=["telemetry"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    categories.router,
    prefix=f"{_V1}/categories",
    tags=["categories"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    environments.router,
    prefix=f"{_V1}/environments",
    tags=["environments"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    discovery_router,
    prefix=f"{_V1}/discovery",
    tags=["discovery"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ws_discovery_router,
    prefix=f"{_V1}/discovery",
    tags=["discovery-ws"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ws_telemetry_router,
    prefix=f"{_V1}/telemetry",
    tags=["telemetry-ws"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ws_topology_router,
    prefix=f"{_V1}/topology",
    tags=["topology-ws"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ip_check_router,
    prefix=f"{_V1}",
    tags=["ip-check"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    settings_router,
    prefix=f"{_V1}/settings",
    tags=["settings"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    system_router,
    prefix=f"{_V1}/system",
    tags=["system"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    branding_router,
    prefix=f"{_V1}/branding",
    tags=["branding"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    assets_router,
    prefix=f"{_V1}/assets",
    tags=["assets"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    admin_router,
    prefix=f"{_V1}/admin",
    tags=["admin"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    admin_audit_router,
    prefix=f"{_V1}/admin",
    tags=["admin-audit"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    admin_users_router,
    prefix=f"{_V1}",
    tags=["admin-users"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    admin_db_router,
    prefix=f"{_V1}/admin",
    tags=["admin-db"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    security_router,
    prefix=f"{_V1}/security",
    tags=["security"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    vault_router,
    prefix=f"{_V1}",
    tags=["vault"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    metrics_router,
    prefix=f"{_V1}/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    timezones_router,
    prefix=f"{_V1}/timezones",
    tags=["timezones"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    rack_api.router,
    prefix=f"{_V1}/racks",
    tags=["racks"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    tags_api.router,
    prefix=f"{_V1}/tags",
    tags=["tags"],
    dependencies=[Depends(require_auth)],
)

app.include_router(
    capabilities_router,
    prefix=f"{_V1}/capabilities",
    tags=["capabilities"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    certificates_router,
    prefix=f"{_V1}/certificates",
    tags=["certificates"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    cve_router,
    prefix=f"{_V1}/cve",
    tags=["cve"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    monitor_router,
    prefix=f"{_V1}/monitors",
    tags=["monitors"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    events_router,
    prefix=f"{_V1}/events",
    tags=["events"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    webhooks_router,
    prefix=f"{_V1}/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    status_router,
    prefix=f"{_V1}/status",
    tags=["status"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ws_status_router,
    prefix=f"{_V1}/status",
    tags=["status-ws"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    notifications_router,
    prefix=f"{_V1}/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_auth)],
)
app.include_router(auth_oauth.router, prefix=f"{_V1}", tags=["oauth"])
app.include_router(
    integration_provider_router,
    prefix=f"{_V1}/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    proxmox_router,
    prefix=f"{_V1}/integrations/proxmox",
    tags=["proxmox"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    topologies_router,
    prefix=f"{_V1}/topologies",
    tags=["topologies"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ipam_router,
    prefix=f"{_V1}/ipam",
    tags=["ipam"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    vlan_router,
    prefix=f"{_V1}/vlans",
    tags=["vlans"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    site_router,
    prefix=f"{_V1}/sites",
    tags=["sites"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    node_relations_router,
    prefix=f"{_V1}/node-relations",
    tags=["node-relations"],
    dependencies=[Depends(require_auth)],
)


# ── Health check ───────────────────────────────────────────────────────────


@app.api_route(f"{_V1}/health", methods=["GET", "HEAD"])
async def health():
    from app.core.redis import redis_health
    from app.core.server_state import ServerState, get_state

    state = get_state()

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # Readiness contract check: discovery endpoints serialize ScanJob.error_reason.
            # If this column is missing (migration drift), report db as error.
            conn.execute(text("SELECT error_reason FROM scan_jobs LIMIT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    redis_ok = await redis_health()
    redis_status = "ok" if redis_ok else "error"

    return {
        "state": state.value,
        "ready": state == ServerState.READY,
        "version": settings.app_version,
        "uptime_s": round(time.time() - SERVER_START_TIME),
        "checks": {
            "db": db_status,
            "redis": redis_status,
        },
    }


# ── Static files & SPA fallback ────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent.parent / "static"
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def _resolve_existing_path(*candidates: str | Path | None) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    return None


def _share_dir_candidate(*parts: str) -> Path | None:
    share_dir = os.environ.get("CB_SHARE_DIR")
    return Path(share_dir).expanduser().joinpath(*parts) if share_dir else None


def _bundle_share_candidate(*parts: str) -> Path:
    return Path(sys.executable).resolve().parent.joinpath("share", *parts)


def _meipass_candidate(*parts: str) -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass).joinpath(*parts) if meipass else None


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


async def _static_cache_middleware(request: Request, call_next):
    """Add Cache-Control for static uploads so browsers cache icons and branding."""
    response = await call_next(request)
    path = request.scope.get("path", "")
    if path.startswith(("/uploads/", "/user-icons/", "/branding/")) and response.status_code == 200:
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    return response


app.middleware("http")(_static_cache_middleware)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_file():
    favicon = _branding_dir_data / _FAVICON_FILENAME
    if favicon.exists():
        return FileResponse(str(favicon), media_type="image/x-icon")
    if _frontend_dir and (_frontend_dir / _FAVICON_FILENAME).exists():
        return FileResponse(str(_frontend_dir / _FAVICON_FILENAME), media_type="image/x-icon")
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

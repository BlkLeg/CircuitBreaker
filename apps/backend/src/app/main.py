import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta  # noqa: F401 — used by models imported transitively
from pathlib import Path

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
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
    windscribe,
)
from app.api import integrations as integrations_api
from app.api import maps as maps_api
from app.api import (
    tags as tags_api,
)
from app.api import telemetry as telemetry_api
from app.api.admin import router as admin_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_db import router as admin_db_router
from app.api.admin_users import router as admin_users_router
from app.api.agents import binary_router as agents_binary_router
from app.api.agents import router as agents_router
from app.api.assets import router as assets_router
from app.api.branding import public_router as branding_public_router
from app.api.branding import router as branding_router
from app.api.capabilities import router as capabilities_router
from app.api.certificates import router as certificates_router
from app.api.cve import router as cve_router
from app.api.discovery import router as discovery_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.integration_provider import router as integration_provider_router
from app.api.ip_check import router as ip_check_router
from app.api.ipam import ipam_router, site_router, vlan_router
from app.api.kb import router as kb_router
from app.api.metrics import router as metrics_router
from app.api.monitor import router as monitor_router
from app.api.notifications import router as notifications_router
from app.api.proxmox import router as proxmox_router
from app.api.security_status import router as security_router
from app.api.settings import router as settings_router
from app.api.static_spa import register as register_static_spa
from app.api.system import router as system_router
from app.api.tenants import router as tenants_router
from app.api.timezones import router as timezones_router
from app.api.topologies import router as topologies_router
from app.api.vault import router as vault_router
from app.api.ws_agents import authenticated_router as ws_agents_authenticated_router
from app.api.ws_agents import unauthenticated_router as ws_agents_unauthenticated_router
from app.api.ws_discovery import router as ws_discovery_router
from app.api.ws_monitors import router as ws_monitors_router
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
from app.core.slo_metrics import HttpMetricsMiddleware
from app.core.sql_hardening import build_audit_partition_sql
from app.core.startup_validation import validate_core_dependencies, validate_startup_secrets
from app.core.time import utcnow
from app.core.write_admission import WriteAdmissionMiddleware
from app.db import models
from app.db.models import IntegrationConfig
from app.db.session import get_session_context
from app.middleware.csrf import CSRFMiddleware
from app.middleware.legacy_token import LegacyTokenMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.proxy_headers import ProxyHeadersMiddleware
from app.middleware.rate_limit_middleware import TenantRateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware, install_request_id_log_filter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant_middleware import TenantMiddleware
from app.startup.scheduler import (
    register_discovery_profile_crons,
    run_discovery_enrichment_backfill,
)
from app.startup.schema import (
    assert_required_schema,
    require_timescale_if_configured,
    run_alembic_upgrade,
    warn_if_rls_without_bypass,
)

# ---------------------------------------------------------------------------
# OAuth param scrubber for uvicorn access logs
# ---------------------------------------------------------------------------
# The OAuth callback URLs carry one-time-use `code` and `state` query params
# that are sensitive — logging them verbatim would allow replaying the flow
# from log files.  This filter replaces their values with [redacted] in
# uvicorn's access log before anything is written to disk.
_OAUTH_SCRUB_RE = re.compile(
    r"(?<=[?&])(?:code|state|cb_auth_code|cb_mfa_token|oauth_token|access_token)=[^& \"]+",
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
# Task 1b (observability phase 2): attaches record.request_id to every log
# record on the same logger set redaction runs on. A parallel installer, not
# a change to install_global_log_redaction — redaction keeps running exactly
# as before, this adds a filter alongside it rather than replacing one.
install_request_id_log_filter()

_logger = logging.getLogger(__name__)


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

    # SRV-02: resolve the process topology once, loudly. A contradiction
    # between CB_TOPOLOGY_MODE and the legacy CB_RUN_INPROCESS_WORKERS is a
    # startup failure, not a coin toss decided later by whichever branch reads
    # its variable first.
    from app.core import topology as _topology
    from app.core import write_admission

    try:
        _topology_mode = _topology.resolve_mode()
    except _topology.TopologyConfigError as _topology_exc:
        _logger.critical("STARTUP FAILED: %s", _topology_exc)
        raise SystemExit(1) from _topology_exc
    _logger.info("[topology] %s", _topology.describe(_topology_mode))

    # SRV-03: from here the lifespan owns the lifecycle state, so the write
    # guard may act on STARTING/STOPPING as well as on dependency failures.
    write_admission.arm()

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
    auto_migrate_enabled = os.environ.get("CB_AUTO_MIGRATE", "true").lower() != "false"
    if auto_migrate_enabled:
        try:
            run_alembic_upgrade()
            _logger.info("Alembic migrations applied (or already at head).")
        except Exception as _me:
            _logger.critical(
                "Auto-migrate failed: %s — fix the database or run "
                "'make migrate' / 'alembic upgrade head', then restart.",
                _me,
                exc_info=True,
            )
            raise SystemExit(1) from _me

    if auto_migrate_enabled:
        assert_required_schema()
    else:
        _logger.info("Schema validation skipped because migrations were pre-applied.")
    require_timescale_if_configured()
    warn_if_rls_without_bypass()

    # ── Phase 1b: Warn if default client hash salt is in use ──────────────
    from app.core.security import _DEFAULT_SALT, get_client_salt

    try:
        with get_session_context() as _salt_db:
            if get_client_salt(_salt_db) == _DEFAULT_SALT:
                _logger.warning(
                    "SECURITY: CB_CLIENT_SALT is not set and no custom salt is stored in "
                    "AppSettings. The default public salt 'circuitbreaker-salt-v1' is in use. "
                    "Set CB_CLIENT_SALT to a unique random value to prevent rainbow table "
                    "attacks on client-side password pre-hashes."
                )
    except Exception:
        pass  # Non-fatal — vault may not be ready yet on first boot

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
            from app.services.settings_service import (
                get_or_create_settings as _settings_for_secrets,
            )

            _startup_cfg = _settings_for_secrets(_vault_db)
            _secret_errors = validate_startup_secrets(
                jwt_secret=_startup_cfg.jwt_secret,
                vault_key=_vault_key,
            )
            if _secret_errors:
                raise RuntimeError("; ".join(_secret_errors))
            if _vault_key:
                _get_vault().reinitialize(_vault_key)
                import os as _os

                _os.environ["CB_VAULT_KEY"] = _vault_key
                _logger.info("Vault initialized from: %s", _vault_svc.get_key_source())
            elif _vault_svc._count_encrypted_secrets(_vault_db) > 0:
                raise RuntimeError(
                    "Vault encryption key is missing but encrypted secrets exist; set CB_VAULT_KEY "
                    "or restore the persisted vault key before startup"
                )
            else:
                _logger.warning(
                    "CB_VAULT_KEY not found in environment, %s, or database. "
                    "Vault is uninitialized — encrypted credentials will be unavailable "
                    "until OOBE completes and a vault key is generated.",
                    _vault_svc._DATA_ENV_PATH,
                )
    except Exception as _ve:
        _logger.critical("Vault init failed during startup: %s", _ve, exc_info=True)
        raise SystemExit(1) from _ve

    # ── Native integration bootstrap ───────────────────────────────────────
    with get_session_context() as _native_db:
        try:
            from app.db.models import Integration as _Integration

            _native = _native_db.query(_Integration).filter(_Integration.type == "native").first()
            if not _native:
                _native = _Integration(
                    type="native",
                    name="Built-in Monitors",
                    enabled=True,
                    sync_interval_s=60,
                )
                _native_db.add(_native)
                _native_db.commit()
                _logger.info("Native integration bootstrapped (id=%d)", _native.id)
            else:
                _logger.debug("Native integration already exists (id=%d)", _native.id)
        except Exception as _ne:
            _logger.warning("Native integration bootstrap failed: %s", _ne)

    # ── Redis (telemetry cache + pub/sub) ────────────────────────────────
    from app.core.redis import close_redis, init_redis

    _redis = await init_redis(settings.redis_url)

    # ── NATS message bus ───────────────────────────────────────────────────
    await nats_client.connect()
    _logger.info("NATS initialised (connected=%s)", nats_client.is_connected)
    try:
        await validate_core_dependencies(_redis, nats_client.is_connected)
    except RuntimeError as _dep_exc:
        _logger.critical("STARTUP FAILED: %s", _dep_exc)
        raise SystemExit(1) from _dep_exc

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

    # ── APScheduler — scheduled discovery jobs ────────────────────────────
    from apscheduler.triggers.cron import CronTrigger

    from app.core.scheduler import SingleOwnerScheduler

    # SRV-02: every job registered below runs on exactly one process, whatever
    # the deployment does with replicas. See SingleOwnerScheduler.
    scheduler = SingleOwnerScheduler()
    from app.core.scheduler import set_scheduler_instance

    # Keep discovery profile reloads/status views pointed at the live runtime scheduler.
    set_scheduler_instance(scheduler)

    # Daily purge of old scan results — and the *only* registration of it.
    # `core.scheduler.reload_discovery_jobs` used to register the same callable
    # on the same 03:00 trigger under a second id, `discovery_purge` (B43), so
    # every discovery-profile write left two jobs running one purge.
    # `SingleOwnerScheduler` keys its advisory lock on the job id, so two ids
    # meant two locks and the copies did not exclude each other; what kept the
    # DELETE from actually running twice at once was the callable's own inner
    # `run_with_advisory_lock("discovery_purge")`, which is not a guarantee the
    # scheduler makes and not one a reader of this call site can see. The visible
    # cost was two `background_job_runs_total{outcome="ran"}` samples a night for
    # one purge; the latent cost was that deleting that inner lock — a reasonable
    # cleanup, since `SingleOwnerScheduler` is meant to make it redundant — turned
    # a duplicate registration into a concurrent double purge.
    #
    # `misfire_grace_time` matches the other nightly crons; see the
    # `daily_db_snapshot` registration below for what it does and does not cover.
    scheduler.add_job(
        discovery_service.purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id="purge_old_scan_results",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # hardware_live_metrics and telemetry_timeseries retention is now managed by
    # TimescaleDB retention policies (migration 0050). Manual DELETE jobs have been
    # removed. If TimescaleDB is not installed, fallback functions remain available
    # in app.services.telemetry_service and app.workers.cleanup.

    # Daily purge of old audit log entries based on retention setting
    from app.services.log_purge import purge_old_audit_logs

    scheduler.add_job(
        purge_old_audit_logs,
        trigger=CronTrigger(hour=3, minute=15),
        id="audit_log_purge",
        replace_existing=True,
    )

    # listener_events is the only discovery table fed directly by unauthenticated
    # LAN traffic: every mDNS advertisement and every SSDP datagram that clears
    # the rate gate appends a row, and nothing removed them. The listener's own
    # admission control bounds the rate, not the total, so on a noisy network the
    # table grows without limit on the same volume that holds pgdata (B13).
    #
    # 03:30 keeps it clear of its neighbours, which matter because
    # SingleOwnerScheduler takes an advisory lock keyed on the job id and a purge
    # that overlaps another purge just queues behind it: scan results run at
    # 03:00, audit logs at 03:15, probe runs at 03:20.
    from app.services.listener_purge import purge_old_listener_events

    scheduler.add_job(
        purge_old_listener_events,
        trigger=CronTrigger(hour=3, minute=30),
        id="listener_event_purge",
        replace_existing=True,
    )

    # Slice 3 §1: probe runs are audit for checks the server did not perform
    # itself and are retained for seven days. Long-term availability stays in
    # telemetry_timeseries and the monitor rollups, so nothing here is the
    # system of record for uptime.
    from app.services.monitoring.probe_reconcile import purge_old_probe_runs

    scheduler.add_job(
        purge_old_probe_runs,
        trigger=CronTrigger(hour=3, minute=20),
        id="monitor_probe_run_purge",
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

    # Auto-reject agents left pending approval for too long (Task 22 gap:
    # expire_stale_pending_agents existed and was unit-tested but was never
    # actually scheduled).
    def _expire_pending_agents_job() -> None:
        from app.services import agent_registry

        with get_session_context() as db:
            count = agent_registry.expire_stale_pending_agents(db)
            if count:
                _logger.info("expired %d stale pending agent(s)", count)

    scheduler.add_job(
        _expire_pending_agents_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="expire_pending_agents",
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

    # Chain any audit entries that a contended audit-chain lock forced into the
    # spool (services/audit_spool.py). Runs often because the spool window is
    # the one stretch where an audit record exists but carries no tamper
    # evidence of its own — the shorter it is, the better. Cheap when idle: one
    # indexed COUNT-shaped read that finds nothing and returns.
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.audit_spool import drain as drain_audit_spool

    scheduler.add_job(
        drain_audit_spool,
        trigger=IntervalTrigger(minutes=1),
        id="audit_spool_drain",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Daily PostgreSQL backup (skipped when pg_dump is not on PATH)
    from app.services.db_backup import backup_postgres

    scheduler.add_job(
        backup_postgres,
        trigger=CronTrigger(hour=3, minute=30),
        id="pg_backup",
        replace_existing=True,
    )

    # Daily full-state snapshot at 02:00 — the tarball that carries the vault
    # key, the uploads and the config, and the only artifact `cb restore`
    # accepts. Registered here rather than in `core.scheduler.reload_discovery_jobs`,
    # which runs only when an administrator writes a discovery profile and first
    # removes every job it registered: a snapshot job added there exists only in
    # the stretch between a profile write and the next restart. Nothing surfaces
    # the gap, because `latest_backup_info()` reports the `pg_backup` artifact
    # scheduled just above — the absence is discovered at restore time, which is
    # the one moment it cannot be repaired.
    #
    # What `misfire_grace_time` buys, precisely, because the first version of
    # this comment got it wrong (R11): it covers a *running* process whose
    # scheduler wakeup lands late — a stalled event loop, a saturated thread
    # pool, a host that was suspended and resumed. APScheduler's default grace
    # is one second, so without it a two-second hiccup at 02:00 drops the
    # night's snapshot and leaves nothing but a log line. It does **not** cover a
    # restart. The scheduler above is constructed fresh on every boot and keeps
    # its jobs in APScheduler's default in-memory store, so a process that was
    # down at 02:00 holds no record that 02:00 happened; misfire grace forgives a
    # fire time the scheduler is holding, and there is none to forgive.
    #
    # Making the restart claim true would take a persistent job store, and that
    # is not a parameter change here: `SingleOwnerScheduler.add_job` hands
    # APScheduler a `functools.wraps` closure, and a persistent store serialises
    # a job by `__module__:__qualname__` — which `wraps` has already rewritten to
    # name the *unwrapped* function. Every job would come back from the store
    # without its advisory lock, and SRV-02 would be silently gone. If a boot-time
    # catch-up is ever wanted, it belongs in an explicit "was last night's
    # snapshot taken?" check, not in this parameter.
    from app.core.scheduler import run_scheduled_snapshot

    scheduler.add_job(
        run_scheduled_snapshot,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_db_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Uptime Kuma integration sync — every 60 seconds
    from apscheduler.triggers.interval import IntervalTrigger

    from app.workers.integration_sync_worker import run_integration_sync_job

    scheduler.add_job(
        run_integration_sync_job,
        trigger=IntervalTrigger(seconds=60),
        id="integration_sync_job",
        replace_existing=True,
    )

    # CVE sync — only scheduled when enabled in settings
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

    # Privacy periodic pass — feed refresh + hostile-network checks + snapshot.
    # Always scheduled; the job itself honors windscribe_enabled and the
    # windscribe_feed_refresh_hours feed-age gate at runtime, so the in-app
    # toggle applies without a restart.
    from app.core.constants import PRIVACY_PERIODIC_INTERVAL_MINUTES
    from app.services.privacy_score import run_privacy_periodic_job

    scheduler.add_job(
        run_privacy_periodic_job,
        trigger=IntervalTrigger(minutes=PRIVACY_PERIODIC_INTERVAL_MINUTES),
        id="privacy_periodic",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Discovery-readiness Phase 2 — self-healing reconciliation. Always
    # scheduled; the job itself no-ops when cb-helperd isn't installed, so
    # the in-app LAN-discovery toggle applies without a restart once it is.
    from app.core.constants import DISCOVERY_RECONCILE_INTERVAL_MINUTES
    from app.services.discovery_reconciler import run_discovery_reconciliation

    scheduler.add_job(
        run_discovery_reconciliation,
        trigger=IntervalTrigger(minutes=DISCOVERY_RECONCILE_INTERVAL_MINUTES),
        id="discovery_reconciler",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Slice 4 D-5 — agent discovery job reconciliation. A *different* concern
    # from the readiness reconciler above, which shares nothing with it but a
    # word: this one expires dispatch leases whose agent went silent, retries
    # jobs parked in `waiting_for_agent` when their agent reconnects, and drains
    # the `queued` backlog that `_schedule_queued_scan_jobs` otherwise strands.
    # Registered here rather than in `core.scheduler.reload_discovery_jobs`,
    # which is re-invoked on every profile write and first removes every job it
    # registered — a job added there is silently unregistered the next time an
    # administrator saves a profile. It holds its own advisory lock.
    from app.services.agent_discovery_reconcile import (
        RECONCILE_INTERVAL_S as AGENT_DISCOVERY_RECONCILE_INTERVAL_S,
    )
    from app.services.agent_discovery_reconcile import (
        run_agent_discovery_reconciliation,
    )

    scheduler.add_job(
        run_agent_discovery_reconciliation,
        trigger=IntervalTrigger(seconds=AGENT_DISCOVERY_RECONCILE_INTERVAL_S),
        id="agent_discovery_reconcile",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # IP Pool refresh every hour
    scheduler.add_job(
        discovery_service.refresh_ip_pool,
        trigger=CronTrigger(minute=0),
        id="refresh_ip_pool",
        replace_existing=True,
        max_instances=1,
    )

    # Load the discovery profiles that are due a cron and schedule them.
    with get_session_context() as sched_db:
        register_discovery_profile_crons(scheduler, sched_db)

    # Uptime monitoring is handled by the item-based polling engine
    # (workers: monitor_scheduler + monitor_poll). The legacy run_all_monitors_job
    # APScheduler loop was retired in the polling-engine migration.
    from apscheduler.triggers.interval import IntervalTrigger as _IT

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
    # Route F9: these five were closures defined here in the lifespan, so
    # nothing could import or test them. They now live in app/jobs/proxmox.py
    # with their health writers; the bodies are unchanged.
    from app.jobs.proxmox import (
        proxmox_full_sync,
        proxmox_node_poll,
        proxmox_rrd_poll,
        proxmox_storage_refresh,
        proxmox_vm_poll,
    )

    with get_session_context() as pxmx_db:
        from sqlalchemy import func

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
                proxmox_node_poll,
                trigger=_IT(seconds=_pxmx_node_s),
                id="proxmox_node_telemetry",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=15,
            )
            scheduler.add_job(
                proxmox_vm_poll,
                trigger=_IT(seconds=_pxmx_vm_s),
                id="proxmox_vm_telemetry",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
            _pxmx_rrd_s = int(os.environ.get("PROXMOX_RRD_POLL_SECONDS", "300"))

            scheduler.add_job(
                proxmox_rrd_poll,
                trigger=_IT(seconds=_pxmx_rrd_s),
                id="proxmox_rrd_telemetry",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                proxmox_storage_refresh,
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
                proxmox_full_sync,
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
        if phase4_settings and getattr(phase4_settings, "arp_enabled", False):
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

    from app.workers.analytics_worker import run_analytics_job, run_retention_job

    scheduler.add_job(
        run_analytics_job,
        trigger=CronTrigger(hour=2, minute=30),
        id="analytics_job",
        replace_existing=True,
    )
    scheduler.add_job(
        run_retention_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="retention_job",
        replace_existing=True,
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

    # ── OPNsense background monitor ───────────────────────────────────────────
    with get_session_context() as _opn_db:
        _opn_settings = _opn_db.query(models.AppSettings).first()
        if _opn_settings and getattr(_opn_settings, "opnsense_enabled", False):
            from app.services.opnsense_monitor import start_monitor as _start_opnsense_monitor

            _opn_cfg = {
                "opnsense_host": getattr(_opn_settings, "opnsense_host", ""),
                "opnsense_api_key_enc": getattr(_opn_settings, "opnsense_api_key_enc", None),
                "opnsense_api_secret_enc": getattr(_opn_settings, "opnsense_api_secret_enc", None),
                "opnsense_verify_ssl": getattr(_opn_settings, "opnsense_verify_ssl", False),
            }
            await _start_opnsense_monitor(_opn_cfg)

    # ── Notification and discovery workers (skip when running with dedicated worker
    # containers, e.g. Docker Compose) ───────────────────────────────────────────
    _run_inprocess_workers = _topology.api_runs_inprocess_workers(_topology_mode)
    _worker_tasks: list = []
    # The subset of _worker_tasks that takes a stop event and cleans up in a
    # `finally` -- currently the telemetry-ingest and integration loops, both of
    # which release a PostgreSQL advisory lease there. They are tracked
    # separately because shutdown has to let them observe the stop event before
    # anything cancels them; see the drain block below for what happens when it
    # does not.
    _draining_tasks: list = []
    _ingest_stop_event = asyncio.Event()
    _integration_stop_event = asyncio.Event()
    if _run_inprocess_workers:
        from app.workers import discovery as discovery_worker
        from app.workers import notification_worker
        from app.workers.telemetry_ingest_worker import run_ingest_loop as _run_ingest_loop

        _worker_tasks.append(asyncio.create_task(notification_worker.run_worker()))
        _worker_tasks.append(asyncio.create_task(discovery_worker.run_worker()))
        _ingest_task = asyncio.create_task(_run_ingest_loop(_ingest_stop_event))
        _worker_tasks.append(_ingest_task)
        _draining_tasks.append(_ingest_task)
        from app.workers.integration_worker import run_integration_worker as _run_integration_worker

        _integration_task = asyncio.create_task(_run_integration_worker(_integration_stop_event))
        _worker_tasks.append(_integration_task)
        _draining_tasks.append(_integration_task)
        _logger.info(
            "Notification, discovery, telemetry ingest, and integration workers started in-process."
        )
    else:
        _logger.info(
            "[topology] mode=%s — %s run as dedicated worker processes, not in the API.",
            _topology_mode.value,
            ", ".join(_topology.INPROCESS_WORKER_FUNCTIONS),
        )

    # ── Phase 9: Update check (non-blocking, daily) ─────────────────────
    # Appended to _worker_tasks so shutdown cancels it. Deliberately outside
    # the inprocess worker conditional: knowing the build is stale is not
    # a worker concern.
    try:
        from app.core.update_check import run_update_check_loop

        _worker_tasks.append(asyncio.create_task(run_update_check_loop()))
    except Exception:
        pass  # Never let update check affect startup

    # ── Phase 10: Discovery readiness logging ──────────────────────────
    # Make degraded discovery (missing nmap, no raw sockets, no ARP, etc.)
    # visible at boot instead of only being discovered at scan time.
    try:
        from app.services.discovery_readiness import log_discovery_readiness_at_startup

        log_discovery_readiness_at_startup()
    except Exception:
        _logger.warning("Discovery readiness logging failed at startup", exc_info=True)

    # ── Phase 11: reconcile the discovery review queue ─────────────────────
    # Reclassify stale new observations, enrich known devices, and consolidate
    # pending duplicates from older builds. The paginated pass is idempotent;
    # unknown devices remain reviewable. Threaded because it owns a synchronous
    # session; a failed backfill is reported without preventing startup.
    try:
        await asyncio.to_thread(run_discovery_enrichment_backfill)
    except Exception:
        _logger.warning("Discovery enrichment backfill failed at startup", exc_info=True)

    # ── Task 1c: event-loop lag sampler (observability phase 2) ────────────
    # A 100ms sleep loop is free, so this runs by default. Appended to
    # _worker_tasks so the cancel-and-gather shutdown below stops it the same
    # way it stops the update-check loop — return_exceptions=True there means
    # a cancelled or failed sampler never raises into this lifespan.
    if os.environ.get("CB_LOOP_LAG_SAMPLER", "true").strip().lower() not in {"false", "0", "no"}:
        from app.core.slo_metrics import run_event_loop_lag_sampler

        _worker_tasks.append(asyncio.create_task(run_event_loop_lag_sampler()))
    else:
        _logger.info("[lifecycle] event loop lag sampler disabled via CB_LOOP_LAG_SAMPLER=false")

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

    # ── Drain, then cancel, in-process worker tasks ───────────────────────
    # Setting the stop event and cancelling in the same block is what this used
    # to do, and it meant the cooperative loops never saw the event: `cancel()`
    # lands before the loop is scheduled again, so the task raises CancelledError
    # at whatever `await` it is parked on. Their `finally` blocks then run in a
    # cancelled task, where the very next `await` -- `lease.release_async()`,
    # which is `asyncio.to_thread(...)` -- raises immediately instead of
    # releasing.
    #
    # The advisory lease therefore stayed held on a session nothing closed. On a
    # rolling restart the replacement process stands by waiting for a lease the
    # departing one never handed over, and the function it guards silently stops
    # happening -- exactly the failure
    # tests/test_srv_drain.py::test_a_restarted_process_can_take_the_lease_the_old_one_held
    # exists to catch, which it did not because it probed only the
    # `scheduled_job` namespace and not `worker_lease`. It surfaced instead as an
    # intermittent failure of tests/test_worker_lease.py two files later in the
    # same CI shard.
    #
    # So: signal, give the cooperative loops a bounded window to exit on their
    # own, and only then cancel. Five seconds sits well inside the unit's
    # TimeoutStopSec=30 and the scheduler's own 10s budget above; the loops park
    # on `wait_for(stop_event.wait(), ...)` and wake immediately, so the window
    # is only ever paid by a worker genuinely mid-batch.
    _WORKER_DRAIN_TIMEOUT_S = 5.0
    _ingest_stop_event.set()
    _integration_stop_event.set()

    if _draining_tasks:
        _, _still_running = await asyncio.wait(_draining_tasks, timeout=_WORKER_DRAIN_TIMEOUT_S)
        if _still_running:
            # Named rather than counted: which loop refused to drain is the first
            # thing anyone debugging a stuck shutdown needs, and it is also how a
            # lease that is still held after this point gets attributed.
            _logger.warning(
                "Worker task(s) did not drain within %ss and will be cancelled — "
                "any lease they hold is released only when this process exits: %s",
                _WORKER_DRAIN_TIMEOUT_S,
                ", ".join(sorted(_t.get_name() for _t in _still_running)),
            )

    for _wt in _worker_tasks:
        _wt.cancel()
    if _worker_tasks:
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
        _logger.info("In-process workers stopped.")

    # ── Stop OPNsense monitor ─────────────────────────────────────────────
    from app.services.opnsense_monitor import cancel_monitor as _cancel_opnsense_monitor

    _cancel_opnsense_monitor()

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

    # SRV-04: the drain is over — admission stopped when the state went
    # STOPPING (above), the scheduler was given its grace period, in-process
    # workers were signalled and awaited, and every lease those workers hold is
    # released with the connection that held it. Releasing the lifecycle gate
    # is the last thing this process's lifespan does; the server has already
    # stopped accepting, so it changes nothing here and keeps a host that
    # reuses the ASGI app after a completed lifecycle from inheriting a
    # permanently closed gate.
    write_admission.disarm()
    _logger.info("[lifecycle] drain complete")


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


def _rate_limit_exceeded_handler_typed(request: Request, exc: Exception) -> Response:
    return _rate_limit_exceeded_handler(request, exc)


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler_typed)

from app.core.otel import init_otel  # noqa: E402

init_otel(app)

# ── CORS ───────────────────────────────────────────────────────────────────
# Default to same-origin only; never allow wildcard origins in production.
_cors_origins = [o for o in (settings.cors_origins or []) if o != "*"]
if not _cors_origins:
    _logger.warning("CORS: no valid origins configured — same-origin only.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    # X-Request-ID is set by the axios client on every request (api/client.jsx).
    # Omitting it here meant that on any split-origin deployment — the case where
    # cors_origins is configured at all — the preflight came back without it and
    # the browser blocked the whole request, not just the header. Same-origin
    # mono installs never preflight, which is why this went unnoticed.
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    # Exposed so the browser can read the id back off the response and correlate
    # it with the server logs, which is the entire point of minting it.
    expose_headers=["X-Request-ID"],
)
app.add_middleware(CSRFMiddleware)
app.add_middleware(LegacyTokenMiddleware)
app.add_middleware(LoggingMiddleware)
# SRV-03: refuse writes the server cannot serve safely. Registered here, which
# puts it *inside* SecurityHeadersMiddleware (so a 503 rejection still carries
# the security headers) and *outside* the audit logger (a refused write changed
# nothing, so there is nothing to audit).
app.add_middleware(WriteAdmissionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TenantRateLimitMiddleware)
app.add_middleware(TenantMiddleware)
# RC-05: the availability and latency indicators. Measures what a client
# actually experienced — including the time spent in every middleware above,
# and responses they produce themselves (a rate-limit 429, a readiness 503).
app.add_middleware(HttpMetricsMiddleware)
# Task 1a (observability phase 2): correlates a browser navigation with the
# server work it caused. Added last of all, so it is now the true outermost
# layer — including outside HttpMetricsMiddleware — because the request ID
# must exist before anything else runs: a request ID minted inside the
# metrics layer could never appear in the metrics layer's own log lines, or
# in any log line any middleware above emits while handling this request.
app.add_middleware(RequestIdMiddleware)
# Added after RequestIdMiddleware, so this — not that — is now the outermost
# layer. It has to be: it rewrites scope["client"] and scope["scheme"] from the
# forwarded headers (the job uvicorn's own ProxyHeadersMiddleware used to do,
# now disabled at every launch site), and everything that reads request.client
# for an audit record must run inside it. It records the pre-rewrite socket
# peer, which is the fact core.forwarded needs and uvicorn's version destroyed.
# See middleware/proxy_headers.py for the full account.
app.add_middleware(ProxyHeadersMiddleware)

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
    windscribe.router,
    prefix=f"{_V1}",
    tags=["windscribe"],
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
# Relationship deletes address a link by its own id, so they mount at the API
# root rather than under /external-nodes/{node_id}. Same auth dependency as the
# router above — the routes themselves also carry require_write_auth.
app.include_router(
    external_nodes.relations_router,
    prefix=_V1,
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
    ws_monitors_router,
    prefix=f"{_V1}/monitors",
    tags=["monitors-ws"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    ws_topology_router,
    prefix=f"{_V1}/topology",
    tags=["topology-ws"],
    dependencies=[Depends(require_auth)],
)
# Deliberately WITHOUT dependencies=[Depends(require_auth)] — the Noise IK
# handshake performed inside /enroll (and /link, added later) is this
# router's authentication. Every other WS router in this file requires a
# session; this one must not.
app.include_router(
    ws_agents_unauthenticated_router,
    prefix=f"{_V1}/agents",
    tags=["agents-ws"],
)
app.include_router(
    ws_agents_authenticated_router,
    prefix=f"{_V1}/agents",
    tags=["agents-ws"],
    dependencies=[Depends(require_auth)],
)
app.include_router(
    agents_router,
    prefix=f"{_V1}/agents",
    tags=["agents"],
    dependencies=[Depends(require_auth)],
)
# Unauthenticated — the agent has no user session; integrity comes from the
# SHA-256 delivered over the Noise-encrypted link, not from route auth.
app.include_router(
    agents_binary_router,
    prefix=f"{_V1}/agents",
    tags=["agents-binary"],
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
    branding_public_router,
    prefix=f"{_V1}/branding",
    tags=["branding"],
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
    kb_router,
    prefix=f"{_V1}/kb",
    tags=["kb"],
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
    tenants_router,
    prefix=f"{_V1}/tenants",
    tags=["tenants"],
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
    integrations_api.router,
    prefix=f"{_V1}/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_auth)],
)

from app.api import intel as intel_api  # noqa: E402

app.include_router(
    intel_api.router,
    prefix=f"{_V1}/intel",
    tags=["intelligence"],
    dependencies=[Depends(require_auth)],
)

app.include_router(
    maps_api.router,
    prefix=f"{_V1}/maps",
    tags=["maps"],
    dependencies=[Depends(require_auth)],
)

from app.api import failed_messages as failed_messages_api  # noqa: E402

# Parked JetStream work (route F14). `require_auth` here and `require_role("admin")`
# on each route: the rows carry raw payloads from the producing system, so the
# per-route admin gate is the security boundary, not the mount.
app.include_router(
    failed_messages_api.router,
    prefix=f"{_V1}/failed-messages",
    tags=["failed-messages"],
    dependencies=[Depends(require_auth)],
)


# ── Health probes ──────────────────────────────────────────────────────────
# Unauthenticated by design: the container HEALTHCHECK, nginx and the frontend
# connectivity poll all read these before any session exists. What they may
# disclose is decided inside the handlers, not by a mount-level dependency.
app.include_router(health_router, prefix=_V1)

# ── Static files & SPA fallback ────────────────────────────────────────────
# Last, and it has to stay last: the fallback claims `GET /{full_path:path}`,
# so any route registered after this call is unreachable.
register_static_spa(app)

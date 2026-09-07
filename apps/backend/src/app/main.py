import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta  # noqa: F401 — used by models imported transitively

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routing import include_all_routers
from app.api.static_spa import register as register_static_spa
from app.core import (
    compat as _compat,  # noqa: F401 — must be first; patches asyncio.iscoroutinefunction before slowapi import
)
from app.core.config import settings
from app.core.errors import AppError
from app.core.log_redaction import install_global_log_redaction
from app.core.rate_limit import limiter
from app.core.security import _log_api_token_deprecation
from app.core.slo_metrics import HttpMetricsMiddleware
from app.core.startup_validation import validate_core_dependencies
from app.core.write_admission import WriteAdmissionMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.legacy_token import LegacyTokenMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.proxy_headers import ProxyHeadersMiddleware
from app.middleware.rate_limit_middleware import TenantRateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware, install_request_id_log_filter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant_middleware import TenantMiddleware
from app.startup.bootstrap import (
    apply_pending_migrations,
    autodetect_api_base_url,
    bootstrap_native_integration,
    init_vault,
    validate_data_dir_writable,
    warn_on_default_client_salt,
)
from app.startup.jobs import register_scheduled_jobs
from app.startup.messaging import subscribe_ws_bridges
from app.startup.scheduler import shutdown_scheduler
from app.startup.workers import (
    drain_background_tasks,
    start_background_tasks,
    stop_listener,
    stop_opnsense_monitor,
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

    # ── Pre-bus startup phases ────────────────────────────────────────────
    # Order is the contract: the volume must be writable before anything
    # writes, the schema must exist before anything reads, and the vault must
    # be loaded before anything encrypts. See app.startup.bootstrap.
    validate_data_dir_writable()
    apply_pending_migrations()
    warn_on_default_client_salt()
    autodetect_api_base_url()
    init_vault()
    bootstrap_native_integration()

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

    # ── NATS → WebSocket bridges ──────────────────────────────────────────
    _lifespan_subs = await subscribe_ws_bridges()

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

    # ── APScheduler — scheduled jobs ──────────────────────────────────────
    # SRV-02: every job `register_scheduled_jobs` adds runs on exactly one
    # process, whatever the deployment does with replicas. See
    # SingleOwnerScheduler; the job list itself is `startup.jobs`.
    from app.core.scheduler import SingleOwnerScheduler, set_scheduler_instance

    scheduler = SingleOwnerScheduler()
    # Keep discovery profile reloads/status views pointed at the live runtime scheduler.
    set_scheduler_instance(scheduler)
    register_scheduled_jobs(scheduler)
    scheduler.start()
    _logger.info("APScheduler started.")

    # ── Background tasks ──────────────────────────────────────────────────
    # Listener, OPNsense poller, in-process workers, update check and the
    # loop-lag sampler. See app.startup.workers for what each one is.
    background = await start_background_tasks(_topology_mode)

    set_state(ServerState.READY)
    _logger.info("[lifecycle] server state → READY")

    yield  # ── app is running ──

    set_state(ServerState.STOPPING)
    _logger.info("[lifecycle] server state → STOPPING")

    await stop_listener()
    await shutdown_scheduler(scheduler)
    await drain_background_tasks(background)
    stop_opnsense_monitor()

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
include_all_routers(app)

# ── Static files & SPA fallback ────────────────────────────────────────────
# Last, and it has to stay last: the fallback claims `GET /{full_path:path}`,
# so any route registered after this call is unreachable.
register_static_spa(app)

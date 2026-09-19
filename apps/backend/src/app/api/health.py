"""Liveness, readiness, startup and legacy combined health probes.

Split out of ``app.main`` with its helpers so the restart contract a container
orchestrator depends on can be read in one screen.  Mounted under ``/api/v1``
by ``main``; the paths and response shapes are unchanged, because the Docker
HEALTHCHECK, nginx, ``deploy/setup.sh`` and the frontend connectivity poll all
read them.
"""

import logging
import time

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.health import HealthSnapshot
from app.db.session import engine, get_db

_logger = logging.getLogger(__name__)

#: Process start, in epoch seconds.  Read by ``/livez`` and ``/health`` to
#: report uptime; set at import so it reflects the process, not the first probe.
SERVER_START_TIME = time.time()

router = APIRouter()


# ── Health check ───────────────────────────────────────────────────────────
#
# Each probe is registered twice: a documented GET and an undocumented HEAD.
# One `api_route(methods=["GET", "HEAD"])` publishes both methods under the
# same operation id, and a duplicate operation id is a generation error in
# every OpenAPI client generator — which is exactly the machine-readable
# contract SRV-01 requires the headless server to publish.


def _health_caller_is_authenticated(request: Request, db: Session) -> bool:
    """Best-effort auth check for deciding how much health detail to disclose.

    Any failure means "treat as anonymous". This endpoint is the Docker
    healthcheck and the frontend's liveness poll, so it must keep answering when
    the database is unreachable — and that is precisely when resolving a user
    will throw. Taking the session as an argument (rather than opening its own)
    is safe for that: `get_db` only constructs a lazily-connecting Session, so
    the dependency itself cannot fail on a down database.
    """
    try:
        from app.core.security import resolve_optional_user_id_sync

        return resolve_optional_user_id_sync(db, request) is not None
    except Exception:
        return False


async def _probe_dependencies() -> dict[str, str]:
    """The dependency half of health, shared by /readyz and legacy /health.

    Kept separate from liveness on purpose: a database or Redis outage means
    "do not send me traffic", not "kill me and start another one". Conflating
    the two is how a dependency blip turns into a restart storm.

    The probe itself lives in `app.core.health`, which is also what the
    write-admission guard consults — one implementation, so what readiness
    reports and what the server actually enforces cannot drift apart.
    """
    from app.core.health import probe_dependencies

    return await probe_dependencies()


async def _health_snapshot() -> HealthSnapshot:
    """Freshly evaluated health for a probe endpoint.

    `max_age_s=0` on purpose: an orchestrator polling every few seconds must
    never be answered out of a cache it has no way to see. The guard on the
    write path is the caching consumer.
    """
    from app.core.health import current_health

    return await current_health(max_age_s=0.0)


@router.head("/livez", include_in_schema=False)
@router.get("/livez")
async def livez() -> dict[str, object]:
    """SRV-03 liveness: is this process able to serve at all?

    Deliberately touches no dependency and takes no lock. If this handler runs,
    the event loop is not wedged, which is the only question a container
    HEALTHCHECK's restart decision should turn on.
    """
    return {"status": "alive", "uptime_s": round(time.time() - SERVER_START_TIME)}


@router.head("/startupz", include_in_schema=False)
@router.get("/startupz")
async def startupz(response: Response) -> dict[str, object]:
    """SRV-03 startup: has initialisation finished?

    Lets an orchestrator hold off its liveness probe during a slow migration
    instead of killing the process mid-upgrade.
    """
    from app.core.server_state import ServerState, get_state

    state = get_state()
    started = state is not ServerState.STARTING
    if not started:
        response.status_code = 503
    return {"state": state.value, "started": started}


@router.head("/readyz", include_in_schema=False)
@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """SRV-03 readiness: can this instance safely serve traffic right now?

    503 while STOPPING is what makes SIGTERM drain work — the load balancer
    stops sending new requests before the process goes away.
    """
    from app.core.server_state import ServerState, get_state

    state = get_state()
    snapshot = await _health_snapshot()
    checks = dict(snapshot.checks)
    ready = state is ServerState.READY and all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = 503
    # `state` stays the lifecycle state it has always been; `health` is the
    # RC-05 health state derived from it and the dependency verdicts, which is
    # the only place a *degraded* server is distinguishable from a not-ready
    # one. `writes_permitted` is not advice — it is what the write-admission
    # guard is enforcing on this process at this moment.
    return {
        "ready": ready,
        "state": state.value,
        "checks": checks,
        "health": snapshot.state.value,
        "degraded": list(snapshot.degraded),
        "writes_permitted": snapshot.writes_permitted,
    }


# `response_model=None` is explicit, not incidental: the return annotation is
# there for mypy, and without this FastAPI would infer a response model from
# it and publish a schema this endpoint has never had. The body shape is
# load-bearing for three external consumers (see the docstring), so it is
# described by them, not by a generated model.
@router.head("/health", include_in_schema=False, response_model=None)
@router.get("/health", response_model=None)
async def health(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    """Legacy combined health, kept at its exact response shape.

    The frontend's connectivity poll, scripts/test-mono-e2e.sh and
    deploy/setup.sh's install-time wait all read this body, so the shape is
    load-bearing. The restart-deciding probes moved to /livez; new consumers
    should use /livez, /readyz or /startupz instead.
    """
    from app.core.server_state import ServerState, get_state

    state = get_state()
    snapshot = await _health_snapshot()
    checks = dict(snapshot.checks)

    body: dict[str, object] = {
        "state": state.value,
        "ready": state == ServerState.READY,
        "uptime_s": round(time.time() - SERVER_START_TIME),
        "checks": checks,
        "health": snapshot.state.value,
        "degraded": list(snapshot.degraded),
    }

    # Build version and installed database extensions are unauthenticated
    # fingerprinting material — they tell a scanner which published CVEs to try
    # before it has any credentials. Liveness (the fields above) is what the
    # healthcheck, the reverse proxy, and the frontend poll actually need, so
    # the detail is reserved for authenticated callers.
    if _health_caller_is_authenticated(request, db):
        timescaledb_available: bool | None = None
        try:
            with engine.connect() as conn:
                timescaledb_available = bool(
                    conn.execute(
                        text(
                            "SELECT 1 FROM pg_available_extensions "
                            "WHERE name = 'timescaledb' LIMIT 1"
                        )
                    ).scalar()
                )
        except Exception:
            # Same contract as before the probe was factored out: a database
            # that cannot answer reports an unknown extension inventory, not a
            # 500 on the endpoint the healthcheck depends on.
            timescaledb_available = None
        body["version"] = settings.app_version
        body["timescaledb_available"] = timescaledb_available

    return body

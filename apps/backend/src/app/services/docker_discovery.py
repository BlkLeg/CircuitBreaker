"""Docker topology discovery service.

Owns the compatibility status/detail entry points and durable sync
orchestration. Enumeration and reconciliation live in focused services.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import DockerSource, DockerSyncRun
from app.db.session import SessionLocal
from app.schemas.docker import DockerSyncRunOut
from app.services.discovery_safe import (
    docker_client,
    is_docker_socket_available,
)
from app.services.docker_enumeration import enumerate_docker
from app.services.docker_reconcile import StaleDockerRun, apply_reconciliation
from app.services.docker_sources import (
    DockerSourceConfigurationError,
    get_or_create_configured_source,
    latest_run,
    resolve_source_config,
    start_sync,
)

_logger = logging.getLogger(__name__)

_DEFAULT_SOCKET_PATH = "/var/run/docker.sock"


def _resolve_docker_base_url(socket_path: str = _DEFAULT_SOCKET_PATH) -> str:
    """Return the Docker daemon base URL, preferring CB_DOCKER_HOST over a local socket.

    If the ``CB_DOCKER_HOST`` env var is set (e.g. ``tcp://proxy:2375``), it is
    used directly — this allows talking to a Docker API proxy instead of mounting
    the raw Docker socket (which grants near-root host access).
    """
    import os

    host = os.environ.get("CB_DOCKER_HOST", "").strip()
    if host:
        return host
    return f"unix://{socket_path}"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_last_sync_result() -> dict:
    """Compatibility projection backed by durable state, not process memory."""
    with SessionLocal() as db:
        source = db.query(DockerSource).order_by(DockerSource.updated_at.desc()).first()
        if source is None:
            return {}
        run = latest_run(db, source.id)
        if run is None:
            return {}
        db.commit()
        db.refresh(run)
        return DockerSyncRunOut.model_validate(run).model_dump(mode="json")


def queue_configured_sync(db: Session, actor: str) -> DockerSyncRun:
    """Resolve the installed source and durably admit one run."""
    from app.services.settings_service import get_or_create_settings

    try:
        config = resolve_source_config(get_or_create_settings(db))
        source = get_or_create_configured_source(db, config)
        run = start_sync(db, source.id, actor)
        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise


def _fail_run(run_id: str, reason_code: str, safe_message: str) -> None:
    with SessionLocal() as db:
        run = db.get(DockerSyncRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        now = datetime.now(UTC)
        source = db.get(DockerSource, run.source_id)
        if source is not None:
            source.last_attempt_at = now
        run.status = "failed"
        run.reason_code = reason_code
        run.safe_message = safe_message
        run.completed_at = now
        run.lease_token = None
        run.lease_expires_at = None
        db.commit()


def _emit_run_result(run_id: str) -> None:
    """Publish committed state for live discovery consumers, best-effort."""
    from app.services.discovery_service import _emit_ws_event

    with SessionLocal() as db:
        run = db.get(DockerSyncRun, run_id)
        if run is None:
            return
        payload = {
            "run_id": run.id,
            "source_id": run.source_id,
            "status": run.status,
            "containers_observed": run.containers_observed,
            "networks_observed": run.networks_observed,
        }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_emit_ws_event("docker_sync_completed", payload))
    else:
        loop.create_task(_emit_ws_event("docker_sync_completed", payload))


def run_source_sync(source_id: int, run_id: str) -> None:
    """Claim a durable run, enumerate without a transaction, then reconcile."""
    from app.services.settings_service import get_or_create_settings

    lease_token = uuid4().hex
    try:
        with SessionLocal() as db:
            run = (
                db.query(DockerSyncRun)
                .filter(
                    DockerSyncRun.id == run_id,
                    DockerSyncRun.source_id == source_id,
                )
                .with_for_update()
                .first()
            )
            source = db.get(DockerSource, source_id)
            if run is None or source is None or run.status != "queued":
                return
            now = datetime.now(UTC)
            if run.lease_expires_at is not None and run.lease_expires_at <= now:
                run.status = "interrupted"
                run.completed_at = now
                run.reason_code = "lease_expired"
                run.safe_message = "The Docker sync worker stopped before completing the run."
                run.lease_expires_at = None
                db.commit()
                _emit_run_result(run_id)
                return
            config = resolve_source_config(get_or_create_settings(db))
            if config.identity != source.identity or run.source_revision != source.revision:
                raise DockerSourceConfigurationError(
                    "Docker source configuration changed before this run started."
                )
            run.status = "running"
            run.started_at = now
            run.lease_token = lease_token
            run.lease_expires_at = now + timedelta(minutes=2)
            source.last_attempt_at = now
            db.commit()
    except DockerSourceConfigurationError:
        _fail_run(
            run_id,
            "source_changed",
            "Docker source configuration changed before this run started.",
        )
        _emit_run_result(run_id)
        return
    except Exception:
        _fail_run(run_id, "run_start_failed", "The Docker sync could not be started.")
        _emit_run_result(run_id)
        return

    enumeration = enumerate_docker(config)
    try:
        with SessionLocal() as db:
            apply_reconciliation(db, source_id, run_id, lease_token, enumeration)
            db.commit()
        _emit_run_result(run_id)
    except StaleDockerRun:
        _fail_run(
            run_id,
            "stale_run",
            "A newer source change or sync superseded this Docker run.",
        )
        _emit_run_result(run_id)
    except Exception:
        _logger.exception("Docker reconciliation failed for run %s", run_id)
        _fail_run(
            run_id,
            "reconciliation_failed",
            "Docker observations could not be reconciled safely.",
        )
        _emit_run_result(run_id)


def sync_docker_topology(
    socket_path: str = _DEFAULT_SOCKET_PATH,
    network_types: list[str] | None = None,
) -> dict:
    """Compatibility synchronous facade backed by a durable source/run."""
    del socket_path, network_types
    try:
        with SessionLocal() as db:
            run = queue_configured_sync(db, "compatibility")
            source_id = run.source_id
            run_id = run.id
        run_source_sync(source_id, run_id)
        with SessionLocal() as db:
            completed = db.get(DockerSyncRun, run_id)
            if completed is None:
                return {"enabled": True, "error": "run_not_found"}
            return {
                "enabled": True,
                "error": None if completed.status == "succeeded" else completed.safe_message,
                "networks_synced": completed.networks_observed,
                "containers_synced": completed.containers_observed,
                "synced_at": completed.completed_at.isoformat()
                if completed.completed_at
                else _utcnow_iso(),
                "run_id": completed.id,
                "status": completed.status,
            }
    except Exception:
        return {
            "enabled": False,
            "error": "Docker sync could not be admitted.",
            "networks_synced": 0,
            "containers_synced": 0,
            "synced_at": _utcnow_iso(),
        }


def get_docker_status(socket_path: str = _DEFAULT_SOCKET_PATH) -> dict:
    """Return quick Docker connectivity status without touching the DB."""
    base_url = _resolve_docker_base_url(socket_path)
    is_tcp = base_url.startswith("tcp://") or base_url.startswith("http")

    if not is_tcp and not is_docker_socket_available(socket_path):
        return {
            "available": False,
            "container_count": 0,
            "network_count": 0,
            "socket_path": socket_path,
            "error": "Docker socket not found",
        }

    try:
        with docker_client(base_url) as client:
            containers = client.containers.list(all=True)
            networks = client.networks.list()
        return {
            "available": True,
            "container_count": len(containers),
            "network_count": len(networks),
            "socket_path": socket_path,
            "error": None,
        }
    except Exception as exc:
        return {
            "available": False,
            "container_count": 0,
            "network_count": 0,
            "socket_path": socket_path,
            "error": str(exc),
        }


def get_container_discovery(container_id: str, socket_path: str = _DEFAULT_SOCKET_PATH) -> dict:
    """Return real-time stats and metadata for a single container."""
    base_url = _resolve_docker_base_url(socket_path)
    is_tcp = base_url.startswith("tcp://") or base_url.startswith("http")

    if not is_tcp and not is_docker_socket_available(socket_path):
        return {"error": "Docker socket not found"}

    try:
        with docker_client(base_url) as client:
            container = client.containers.get(container_id)

            # Get stats (non-blocking if stream=False)
            stats = container.stats(stream=False)

            # Basic CPU calculation (handles Linux; Windows differs)
            cpu_pct = 0.0
            try:
                cpu_stats = stats.get("cpu_stats", {})
                precpu_stats = stats.get("precpu_stats", {})

                cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get(
                    "cpu_usage", {}
                ).get("total_usage", 0)
                system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get(
                    "system_cpu_usage", 0
                )

                online_cpus = cpu_stats.get("online_cpus")
                if online_cpus is None:
                    online_cpus = len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", []))

                if system_delta > 0.0 and cpu_delta > 0.0:
                    cpu_pct = (cpu_delta / system_delta) * online_cpus * 100.0
            except (KeyError, ZeroDivisionError, TypeError):
                pass

            # Memory calculation
            mem_usage = stats.get("memory_stats", {}).get("usage", 0)
            mem_limit = stats.get("memory_stats", {}).get("limit", 0)
            mem_pct = (mem_usage / mem_limit) * 100.0 if mem_limit > 0 else 0.0

            # Accurate status detection
            raw_status = container.attrs.get("State", {}).get("Status", container.status)
            status = _normalise_status(raw_status)

            return {
                "id": container.short_id,
                "full_id": container.id,
                "name": container.name,
                "status": status,
                "raw_status": raw_status,
                "image": (container.image.tags or [None])[0],
                "created": container.attrs.get("Created", ""),
                "cpu_pct": round(cpu_pct, 2),
                "mem_usage": mem_usage,
                "mem_limit": mem_limit,
                "mem_pct": round(mem_pct, 2),
                "networks": container.attrs.get("NetworkSettings", {}).get("Networks", {}),
                "ports": container.attrs.get("NetworkSettings", {}).get("Ports", {}),
            }
    except Exception as exc:
        return {"error": str(exc)}


def _normalise_status(docker_status: str) -> str:
    mapping = {
        "running": "running",
        "healthy": "running",
        "starting": "degraded",
        "exited": "stopped",
        "paused": "stopped",
        "restarting": "degraded",
        "dead": "stopped",
        "created": "stopped",
        "removing": "stopped",
    }
    return mapping.get(docker_status.lower(), "unknown")


def _run_docker_sync_job_impl() -> None:
    """Load settings and run Docker topology sync (called under advisory lock)."""
    from app.db.models import AppSettings
    from app.db.session import SessionLocal as _SL

    db = _SL()
    try:
        s = db.query(AppSettings).first()
        if s is None or not s.docker_discovery_enabled:
            return
        socket_path = s.docker_socket_path or _DEFAULT_SOCKET_PATH
        self_cluster = getattr(s, "self_cluster_enabled", False)
    finally:
        db.close()

    sync_docker_topology(socket_path=socket_path)

    if self_cluster:
        from app.services.self_discovery import autocreate_self_cluster

        cluster_db = _SL()
        try:
            autocreate_self_cluster(cluster_db)
        except Exception:
            _logger.exception("Self-cluster auto-create failed after docker sync.")
        finally:
            cluster_db.close()


def run_docker_sync_job() -> None:
    """APScheduler entry point; the scheduler already owns the single-owner lock."""
    _run_docker_sync_job_impl()

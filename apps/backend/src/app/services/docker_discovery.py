"""Docker topology discovery service.

Calls docker_discover() from discovery_safe.py and persists the results
to the DB by upserting Network rows (docker networks) and Service rows
(containers).  The service is intentionally synchronous so it can be called
from APScheduler without an async wrapper.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Network, Service
from app.db.session import SessionLocal
from app.services.discovery_safe import docker_discover, is_docker_socket_available

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


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug without external dependencies."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


_last_sync_result: dict = {}


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_last_sync_result() -> dict:
    return _last_sync_result


def sync_docker_topology(
    socket_path: str = _DEFAULT_SOCKET_PATH,
    network_types: list[str] | None = None,
) -> dict:
    """Enumerate Docker networks and containers; upsert into DB.

    Returns a summary dict: {networks_synced, containers_synced, error}.
    """
    global _last_sync_result

    if not is_docker_socket_available(socket_path):
        result: dict = {
            "enabled": False,
            "error": f"Docker socket not found at {socket_path}",
            "networks_synced": 0,
            "containers_synced": 0,
            "synced_at": _utcnow_iso(),
        }
        _last_sync_result = result
        return result

    raw = docker_discover(
        socket_path=socket_path,
        network_types=network_types,
        enable_port_scan=False,
    )

    # Separate the network_topology sentinel from container dicts
    network_topology_entry: dict | None = None
    containers: list[dict] = []
    for item in raw:
        if item.get("type") == "network_topology":
            network_topology_entry = item
        else:
            containers.append(item)

    db: Session = SessionLocal()
    networks_synced = 0
    containers_synced = 0

    try:
        # ── Upsert Networks ──────────────────────────────────────────────────
        if network_topology_entry:
            for net_info in network_topology_entry.get("networks", []):
                net_name = net_info.get("name", "").strip()
                # Build a stable docker_network_id from the source data.
                # docker_discover() stores nets keyed by net.id but the
                # topology list loses the key — use name+driver as identity.
                docker_id = f"docker-{net_info.get('name', '')}"

                existing = db.query(Network).filter(Network.docker_network_id == docker_id).first()
                if existing is None:
                    new_net = Network(
                        name=net_name or f"docker-net-{docker_id[-8:]}",
                        docker_network_id=docker_id,
                        docker_driver=net_info.get("driver"),
                        is_docker_network=True,
                        cidr=net_info.get("subnet") or None,
                        gateway=net_info.get("gateway") or None,
                        description=f"Docker {net_info.get('driver', '')} network",
                    )
                    db.add(new_net)
                else:
                    existing.docker_driver = net_info.get("driver")
                    existing.is_docker_network = True
                    if net_info.get("subnet"):
                        existing.cidr = net_info["subnet"]
                    if net_info.get("gateway"):
                        existing.gateway = net_info["gateway"]
                    existing.updated_at = utcnow()
                networks_synced += 1

        # ── Upsert Services (containers) ─────────────────────────────────────
        seen_container_ids: set[str] = set()

        for cdata in containers:
            container_id = cdata.get("full_id") or cdata.get("container_id")
            if not container_id:
                continue

            seen_container_ids.add(container_id)
            name = cdata.get("name", "").lstrip("/")
            image = cdata.get("image") or ""
            status = cdata.get("status", "unknown")

            # Primary lookup: match by stable container ID
            existing_svc = (
                db.query(Service).filter(Service.docker_container_id == container_id).first()
            )

            # Secondary lookup: container was recreated and has a new ID.
            # Find by name among existing docker-tracked services and adopt the
            # new ID onto the existing row rather than creating a duplicate.
            if existing_svc is None and name:
                existing_svc = (
                    db.query(Service)
                    .filter(
                        Service.name == name,
                        Service.is_docker_container == True,  # noqa: E712
                    )
                    .first()
                )
                if existing_svc is not None:
                    _logger.info(
                        "Container '%s' appears to have been recreated "
                        "(old id=%s, new id=%s) — updating ID in place.",
                        name,
                        existing_svc.docker_container_id,
                        container_id,
                    )
                    existing_svc.docker_container_id = container_id

            if existing_svc is None:
                base_slug = _slugify(name or f"container-{container_id[:8]}")
                # Ensure unique slug
                slug = base_slug
                counter = 1
                while db.query(Service).filter(Service.slug == slug).first():
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                labels = cdata.get("labels") or {}
                new_svc = Service(
                    name=name or f"container-{container_id[:8]}",
                    slug=slug,
                    docker_container_id=container_id,
                    docker_image=image,
                    docker_labels=labels,
                    is_docker_container=True,
                    status=_normalise_status(status),
                    ip_address=cdata.get("ip"),
                    description=f"Docker container — image: {image}",
                )
                db.add(new_svc)
            else:
                existing_svc.status = _normalise_status(status)
                existing_svc.docker_image = image
                existing_svc.docker_labels = cdata.get("labels") or {}
                existing_svc.is_docker_container = True
                if cdata.get("ip"):
                    existing_svc.ip_address = cdata["ip"]
                existing_svc.updated_at = utcnow()
            containers_synced += 1

        # ── Mark stale containers as stopped ────────────────────────────────
        # Any docker-tracked service whose container ID was NOT seen in this
        # sync pass is no longer running. Mark it stopped so the map reflects
        # reality without deleting user data.
        if seen_container_ids:
            stale_svcs = (
                db.query(Service)
                .filter(
                    Service.is_docker_container == True,  # noqa: E712
                    Service.docker_container_id.notin_(seen_container_ids),
                    Service.status != "stopped",
                )
                .all()
            )
            for stale in stale_svcs:
                stale.status = "stopped"
                stale.updated_at = utcnow()
                _logger.debug("Marked stale container '%s' as stopped.", stale.name)

        db.commit()
    except Exception as exc:
        db.rollback()
        _logger.exception("Docker topology sync failed: %s", exc)
        result = {
            "enabled": True,
            "error": str(exc),
            "networks_synced": 0,
            "containers_synced": 0,
            "synced_at": _utcnow_iso(),
        }
        _last_sync_result = result
        return result
    finally:
        db.close()

    result = {
        "enabled": True,
        "error": None,
        "networks_synced": networks_synced,
        "containers_synced": containers_synced,
        "synced_at": _utcnow_iso(),
    }
    _last_sync_result = result
    _logger.info(
        "Docker sync complete — %d networks, %d containers",
        networks_synced,
        containers_synced,
    )
    return result


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
        import docker

        client = docker.DockerClient(base_url=base_url)
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


def _normalise_status(docker_status: str) -> str:
    mapping = {
        "running": "running",
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
    """APScheduler entry point. Single-run via advisory lock."""
    from app.core.job_lock import run_with_advisory_lock

    run_with_advisory_lock("docker_topology_sync", job_fn=_run_docker_sync_job_impl)

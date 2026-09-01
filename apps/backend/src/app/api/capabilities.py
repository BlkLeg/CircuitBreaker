"""Capabilities endpoint — reports which optional subsystems are active.

GET /api/v1/capabilities  (no auth required — needed pre-login for OOBE)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.db.session import get_db
from app.services.discovery_safe import is_docker_socket_available

router = APIRouter(tags=["capabilities"])

_DEFAULT_SOCKET = "/var/run/docker.sock"


@dataclass(frozen=True)
class _CapabilitySettings:
    """The settings-derived half of the capabilities response, as plain data.

    A snapshot rather than the `AppSettings` row itself, because the row is
    read inside a threadpool worker (route slice 2.5) and handing the event
    loop a live ORM instance would put every attribute read back on the loop —
    and would risk a lazy refresh through a `Session` the loop does not own at
    that moment.

    `present` distinguishes "there is no settings row yet" (a fresh install,
    mid-OOBE) from "the row says everything is off". The two produce different
    responses: with no row the endpoint reports NATS as unavailable without
    consulting the client, and the mDNS/SSDP defaults invert. Collapsing them
    would change the pre-login payload.
    """

    present: bool
    realtime_enabled: bool
    realtime_transport: str
    cve_enabled: bool
    cve_last_sync: str | None
    listener_enabled: bool
    mdns_enabled: bool
    ssdp_enabled: bool
    docker_available: bool
    docker_discovery_enabled: bool


def _read_capability_settings(db: Session) -> _CapabilitySettings:
    """Read the settings row and probe the Docker socket, off the event loop.

    Both halves block: the query is a synchronous `Session` read, and
    `is_docker_socket_available` stats a path that can be a dead NFS or a
    stopped Docker Desktop VM socket. This runs via `run_in_threadpool` at the
    single call site below.
    """
    from app.db.models import AppSettings

    s = db.query(AppSettings).first()
    if s is None:
        return _CapabilitySettings(
            present=False,
            realtime_enabled=False,
            realtime_transport="auto",
            cve_enabled=False,
            cve_last_sync=None,
            listener_enabled=False,
            mdns_enabled=False,
            ssdp_enabled=False,
            docker_available=False,
            docker_discovery_enabled=False,
        )

    socket_path = getattr(s, "docker_socket_path", None) or _DEFAULT_SOCKET
    return _CapabilitySettings(
        present=True,
        realtime_enabled=bool(s.realtime_notifications_enabled),
        realtime_transport=s.realtime_transport,
        cve_enabled=bool(s.cve_sync_enabled),
        cve_last_sync=s.cve_last_sync_at,
        listener_enabled=bool(getattr(s, "listener_enabled", False)),
        mdns_enabled=bool(getattr(s, "mdns_enabled", True)),
        ssdp_enabled=bool(getattr(s, "ssdp_enabled", True)),
        docker_available=is_docker_socket_available(socket_path),
        docker_discovery_enabled=bool(s.docker_discovery_enabled),
    )


@router.get("")
async def get_capabilities(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a map of optional subsystem availability and configuration."""
    settings = await run_in_threadpool(_read_capability_settings, db)

    redis_client = await get_redis()

    return {
        # Only consulted once a settings row exists: a fresh install reports
        # NATS unavailable regardless of what the client thinks, which is what
        # this endpoint has always done.
        "nats": {
            "available": nats_client.is_connected if settings.present else False,
        },
        "redis": {
            "available": redis_client is not None,
        },
        "realtime": {
            "available": settings.realtime_enabled,
            "transport": settings.realtime_transport,
        },
        "cve": {
            "available": settings.cve_enabled,
            "last_sync": settings.cve_last_sync,
        },
        "listener": {
            "available": settings.listener_enabled,
            "mdns": settings.mdns_enabled,
            "ssdp": settings.ssdp_enabled,
        },
        "docker": {
            "available": settings.docker_available,
            "discovery_enabled": settings.docker_discovery_enabled,
        },
        "auth": {
            "enabled": True,
        },
    }

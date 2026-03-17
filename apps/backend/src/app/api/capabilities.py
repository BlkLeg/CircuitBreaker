"""Capabilities endpoint — reports which optional subsystems are active.

GET /api/v1/capabilities  (no auth required — needed pre-login for OOBE)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.db.session import get_db
from app.services.discovery_safe import is_docker_socket_available

router = APIRouter(tags=["capabilities"])

_DEFAULT_SOCKET = "/var/run/docker.sock"


@router.get("")
async def get_capabilities(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a map of optional subsystem availability and configuration."""
    from app.db.models import AppSettings

    s = db.query(AppSettings).first()

    redis_client = await get_redis()

    if s is None:
        return {
            "nats": {"available": False},
            "redis": {"available": redis_client is not None},
            "realtime": {"available": False, "transport": "auto"},
            "cve": {"available": False, "last_sync": None},
            "listener": {"available": False, "mdns": False, "ssdp": False},
            "docker": {"available": False, "discovery_enabled": False},
            "auth": {"enabled": True},
        }

    socket_path = getattr(s, "docker_socket_path", None) or _DEFAULT_SOCKET

    return {
        "nats": {
            "available": nats_client.is_connected,
        },
        "redis": {
            "available": redis_client is not None,
        },
        "realtime": {
            "available": bool(s.realtime_notifications_enabled),
            "transport": s.realtime_transport,
        },
        "cve": {
            "available": bool(s.cve_sync_enabled),
            "last_sync": s.cve_last_sync_at,
        },
        "listener": {
            "available": bool(getattr(s, "listener_enabled", False)),
            "mdns": bool(getattr(s, "mdns_enabled", True)),
            "ssdp": bool(getattr(s, "ssdp_enabled", True)),
        },
        "docker": {
            "available": is_docker_socket_available(socket_path),
            "discovery_enabled": bool(s.docker_discovery_enabled),
        },
        "auth": {
            "enabled": True,
        },
    }

"""The NATS-to-WebSocket bridges the API process subscribes at startup.

Two fan-outs, both secondary delivery paths: topology events reach the topology
WS manager, and discovery events reach discovery WS clients. Redis pub/sub is
the primary cross-worker mechanism for regular scans; this bridge is what
carries events that were published on the bus instead.

The subscriptions are returned rather than held here so the lifespan can
unsubscribe them explicitly on the way down — a bridge that outlives its
process's WS managers delivers into closed sockets.
"""

import json
import logging
from typing import Any

from app.core import subjects as _subj
from app.core.nats_client import nats_client

_logger = logging.getLogger(__name__)


async def subscribe_ws_bridges() -> list:
    """Subscribe the topology and discovery bridges; return the subscriptions.

    Returns an empty list when NATS is not connected, which is a supported
    deployment (single process, Redis-only fan-out), not a failure.
    """
    # Subscribe to topology subjects and fan out to topology WS clients.
    # Also subscribe to notification subjects for SSE fan-out (events.py handles
    # its own subscriptions; this bridge feeds the topology WS manager).
    subs: list = []
    if not nats_client.is_connected:
        return subs

    from app.api.ws_topology import topology_ws_manager

    async def _topo_handler(msg: Any) -> None:
        try:
            data = json.loads(msg.data.decode())
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
            subs.append(_sub)
    _logger.info("NATS → topology WS bridge subscribed.")

    # ── NATS → discovery WebSocket bridge ─────────────────────────────
    # Forwards ALL discovery events (both Proxmox and regular network
    # scans) to discovery WS clients.  This is a secondary delivery
    # path — Redis pub/sub is the primary cross-worker mechanism for
    # regular scans.  Proxmox events that arrive via NATS are mapped
    # to their specific WS message types; regular discovery events are
    # forwarded using their embedded ``event_type``.
    from app.core.ws_manager import ws_manager

    async def _discovery_scan_handler(msg: Any) -> None:
        try:
            data = json.loads(msg.data.decode())
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
            subs.append(_sub)
    _logger.info("NATS → discovery WS bridge subscribed.")
    return subs

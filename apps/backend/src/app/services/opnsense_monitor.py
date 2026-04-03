"""OPNsense background monitor — polls ARP + DHCP leases and updates device states.

Polls ARP every 60s (configurable). When a known Hardware node appears or
disappears from the ARP table, its status is updated and a WebSocket
``device:state_change`` event is broadcast so the frontend map updates live.

Leases are polled every 5 minutes to detect new devices and hostname/IP changes.

Start this task from lifespan() when opnsense_enabled=True.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_ARP_POLL_INTERVAL = 60  # seconds
_LEASE_POLL_INTERVAL = 300  # seconds (5 min)

# Global handle so lifespan can cancel on shutdown or settings change.
_monitor_task: asyncio.Task | None = None


def get_monitor_task() -> asyncio.Task | None:
    return _monitor_task


def cancel_monitor() -> None:
    """Cancel the running monitor task (called when settings change or on shutdown)."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        logger.info("OPNsense monitor cancelled.")
    _monitor_task = None


async def start_monitor(settings_dict: dict) -> None:
    """Create and store the monitor background task."""
    global _monitor_task
    cancel_monitor()
    _monitor_task = asyncio.create_task(_run_monitor_loop(settings_dict), name="opnsense_monitor")
    logger.info(
        "OPNsense monitor started (ARP every %ds, leases every %ds).",
        _ARP_POLL_INTERVAL,
        _LEASE_POLL_INTERVAL,
    )


async def _run_monitor_loop(settings_dict: dict) -> None:
    """Main polling loop. Runs until cancelled."""
    arp_tick: float = 0
    lease_tick: float = 0

    while True:
        now = asyncio.get_event_loop().time()

        if now - arp_tick >= _ARP_POLL_INTERVAL:
            arp_tick = now
            await _poll_arp(settings_dict)

        if now - lease_tick >= _LEASE_POLL_INTERVAL:
            lease_tick = now
            await _poll_leases(settings_dict)

        await asyncio.sleep(10)  # check every 10s; real work only when interval elapsed


async def _poll_arp(settings_dict: dict) -> None:
    """Fetch ARP table and update Hardware.status for known devices."""
    import httpx

    from app.services.discovery_opnsense import _ARP_PATH, _build_client_kwargs

    try:
        base_url, api_key, api_secret, verify_ssl = _build_client_kwargs(settings_dict)
    except (ValueError, Exception) as exc:
        logger.warning("OPNsense monitor: settings error — %s", exc)
        return

    try:
        async with httpx.AsyncClient(
            auth=(api_key, api_secret),
            verify=verify_ssl,
            timeout=10.0,
        ) as client:
            resp = await client.get(f"{base_url}{_ARP_PATH}")
            if resp.status_code != 200:
                logger.warning("OPNsense monitor: ARP poll returned HTTP %d", resp.status_code)
                return
            arp_data = resp.json()
    except Exception as exc:
        logger.warning("OPNsense monitor: ARP poll failed — %s", exc)
        return

    arp_rows = arp_data if isinstance(arp_data, list) else arp_data.get("rows", [])
    active_ips: set[str] = {
        (entry.get("ip") or "").strip() for entry in arp_rows if (entry.get("ip") or "").strip()
    }

    await _apply_arp_state_changes(active_ips)


async def _apply_arp_state_changes(active_ips: set[str]) -> None:
    """Compare live ARP IPs against Hardware records; update status + emit WS events."""
    from app.db.models import Hardware
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        hardware_list = db.query(Hardware).filter(Hardware.ip_address.isnot(None)).all()

        changed: list[dict] = []
        now_str = datetime.now(UTC).isoformat()

        for hw in hardware_list:
            ip = (hw.ip_address or "").strip()
            if not ip:
                continue

            new_status = "online" if ip in active_ips else "offline"
            if hw.status != new_status:
                hw.status = new_status
                if new_status == "online":
                    hw.last_seen = now_str
                changed.append({"id": hw.id, "ip": ip, "status": new_status})

        if changed:
            db.commit()
            logger.debug("OPNsense monitor: %d device state(s) changed", len(changed))
            await _broadcast_state_changes(changed)
    except Exception as exc:
        logger.warning("OPNsense monitor: DB update failed — %s", exc)
        db.rollback()
    finally:
        db.close()


async def _broadcast_state_changes(changes: list[dict]) -> None:
    """Emit device:state_change WebSocket events for each changed device."""
    try:
        from app.core.ws_manager import ws_manager

        for change in changes:
            await ws_manager.broadcast(
                {
                    "type": "device:state_change",
                    "id": change["id"],
                    "ip": change["ip"],
                    "status": change["status"],
                }
            )
    except Exception as exc:
        logger.warning("OPNsense monitor: WS broadcast failed — %s", exc)


async def _poll_leases(settings_dict: dict) -> None:
    """Fetch DHCP leases and log new/changed devices (does not auto-import)."""
    from app.services.discovery_opnsense import fetch_opnsense_devices

    devices, err = await fetch_opnsense_devices(settings_dict)
    if err:
        logger.warning("OPNsense monitor: lease poll failed — %s", err)
        return

    if devices:
        logger.debug(
            "OPNsense monitor: lease poll found %d devices (%d active)",
            len(devices),
            sum(1 for d in devices if d.get("is_active")),
        )

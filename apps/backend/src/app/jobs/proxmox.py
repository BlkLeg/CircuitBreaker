"""Scheduled Proxmox integration jobs, and the health writers they use.

Route F9: these five were closures nested inside `main.py`'s lifespan, so
nothing could import them and nothing could test them. The bodies are unchanged
— this module moves them, it does not rewrite them — with two deliberate
differences:

- The timeouts are module constants rather than literals, so a test can shorten
  one and actually reach the guard. Reaching it before meant booting the app and
  waiting sixty seconds.
- `record_poll_health` and `record_sync_health` came along. They lived in
  `main.py` and were called from nowhere else, so leaving them behind would have
  made `app.jobs` import `app.main` — an import cycle, and a much worse one than
  the duplication it would avoid.

Every job swallows its own `TimeoutError`. That is not sloppiness: APScheduler
runs these `max_instances=1`, so a poll that hangs would block every later run
of the same job. Skipping the cycle with a warning keeps the schedule alive and
leaves a trace, where letting the exception out would mark the run errored and
tell an operator a poll crashed when it merely ran long.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.time import utcnow
from app.db.async_session import AsyncSessionLocal
from app.db.models import IntegrationConfig
from app.db.session import get_session_context
from app.services.proxmox_service import (
    discover_and_import,
    list_integrations,
    poll_node_telemetry,
    poll_rrd_telemetry,
    poll_vm_telemetry,
    refresh_proxmox_storage,
)

_logger = logging.getLogger(__name__)

#: Per-job timeout budgets, in seconds. Named so tests can reach the guard.
NODE_POLL_TIMEOUT_S = 60
VM_POLL_TIMEOUT_S = 100
RRD_POLL_TIMEOUT_S = 270
STORAGE_REFRESH_TIMEOUT_S = 270
FULL_SYNC_TIMEOUT_S = 270


def record_sync_health(
    config_id: int,
    result: dict | None = None,
    exc: Exception | None = None,
) -> None:
    """Persist sync outcome to IntegrationConfig. Opens its own session — safe after rollbacks."""
    try:
        with get_session_context() as _hdb:
            cfg = _hdb.get(IntegrationConfig, config_id)
            if not cfg:
                return
            if exc is not None:
                cfg.last_sync_status = "error"
                cfg.last_sync_error = str(exc)[:512]
            elif result is not None:
                errors = result.get("errors") or []
                if not result.get("ok", True):
                    # discover_and_import caught a hard failure internally and returned ok=False
                    cfg.last_sync_status = "error"
                    cfg.last_sync_error = (
                        "\n".join(str(e) for e in errors[:5]) if errors else "Sync failed"
                    )
                else:
                    cfg.last_sync_status = "partial" if errors else "ok"
                    cfg.last_sync_error = "\n".join(str(e) for e in errors[:5]) if errors else None
            cfg.last_sync_at = utcnow()
            _hdb.commit()
    except Exception:
        _logger.exception("Failed to record sync health for config %s", config_id)


def record_poll_health(poll_outcomes: dict[int, Exception | None]) -> None:
    """Write last_poll_error to IntegrationConfig for each config in poll_outcomes."""
    for config_id, exc in poll_outcomes.items():
        try:
            with get_session_context() as _hdb:
                cfg = _hdb.get(IntegrationConfig, config_id)
                if not cfg:
                    continue
                cfg.last_poll_error = str(exc)[:512] if exc is not None else None
                _hdb.commit()
        except Exception:
            _logger.exception("Failed to record poll health for config %s", config_id)


async def proxmox_node_poll() -> None:
    """Poll node-level telemetry for every configured Proxmox integration."""
    try:
        async with asyncio.timeout(NODE_POLL_TIMEOUT_S):
            async with AsyncSessionLocal() as _pdb:
                poll_outcomes = await poll_node_telemetry(_pdb)
                record_poll_health(poll_outcomes)
    except TimeoutError:
        _logger.warning("proxmox_node_poll timed out (%ss) — skipping cycle", NODE_POLL_TIMEOUT_S)


async def proxmox_vm_poll() -> None:
    """Poll per-VM telemetry for every configured Proxmox integration."""
    try:
        async with asyncio.timeout(VM_POLL_TIMEOUT_S):
            async with AsyncSessionLocal() as _pdb:
                poll_outcomes = await poll_vm_telemetry(_pdb)
                record_poll_health(poll_outcomes)
    except TimeoutError:
        _logger.warning("proxmox_vm_poll timed out (%ss) — skipping cycle", VM_POLL_TIMEOUT_S)


async def proxmox_rrd_poll() -> None:
    """Poll RRD history for every configured Proxmox integration."""
    try:
        async with asyncio.timeout(RRD_POLL_TIMEOUT_S):
            async with AsyncSessionLocal() as _pdb:
                poll_outcomes = await poll_rrd_telemetry(_pdb)
                record_poll_health(poll_outcomes)
    except TimeoutError:
        _logger.warning("proxmox_rrd_poll timed out (%ss) — skipping cycle", RRD_POLL_TIMEOUT_S)


async def proxmox_storage_refresh() -> None:
    """Refresh Proxmox storage inventory."""
    try:
        async with asyncio.timeout(STORAGE_REFRESH_TIMEOUT_S):
            async with AsyncSessionLocal() as _pdb:
                await refresh_proxmox_storage(_pdb)
    except TimeoutError:
        _logger.warning(
            "proxmox_storage_refresh timed out (%ss) — skipping cycle",
            STORAGE_REFRESH_TIMEOUT_S,
        )


async def proxmox_full_sync() -> None:
    """Re-import every auto-syncing Proxmox integration.

    Failures are caught per config so one unreachable cluster cannot abort the
    sweep for the others — the same reason the JetStream workers ask a
    per-message question rather than a per-batch one.
    """
    try:
        async with asyncio.timeout(FULL_SYNC_TIMEOUT_S):
            with get_session_context() as _pdb:
                configs = list_integrations(_pdb)
                for cfg in configs:
                    if cfg.auto_sync:
                        try:
                            result = await discover_and_import(_pdb, cfg, queue_for_review=False)
                            record_sync_health(cfg.id, result=result)
                        except Exception as exc:
                            _logger.warning("Proxmox full sync failed for %d: %s", cfg.id, exc)
                            record_sync_health(cfg.id, exc=exc)
    except TimeoutError:
        _logger.warning("proxmox_full_sync timed out (%ss) — skipping cycle", FULL_SYNC_TIMEOUT_S)

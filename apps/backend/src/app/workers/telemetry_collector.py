from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from types import SimpleNamespace
from typing import Any

from app.core.time import utcnow
from app.db.models import Hardware
from app.db.session import get_session_context
from app.integrations.dispatcher import poll_hardware
from app.services.credential_vault import get_vault
from app.services.telemetry_service import write_telemetry
from app.services.vault_service import load_vault_key

logger = logging.getLogger(__name__)


def _safe_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            return None
    return None


def _is_enabled_config(config: dict[str, Any] | None) -> bool:
    if not config:
        return False
    if not config.get("profile") or not config.get("host"):
        return False
    return bool(config.get("enabled", True))


def _coerce_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = 30
    return max(10, interval)


def _init_vault() -> None:
    with get_session_context() as db:
        key = load_vault_key(db)
    if key:
        get_vault().reinitialize(key)
        logger.info("Telemetry collector vault initialized.")
    else:
        logger.warning(
            "Telemetry collector could not load CB_VAULT_KEY from env/file/db; "
            "polls requiring encrypted credentials may fail."
        )


def _discover_devices(default_interval_s: int) -> list[dict[str, Any]]:
    now = utcnow()
    devices: list[dict[str, Any]] = []
    with get_session_context() as db:
        rows = db.query(Hardware).filter(Hardware.telemetry_config.isnot(None)).all()
        for hw in rows:
            config = _safe_json(hw.telemetry_config)
            if not _is_enabled_config(config):
                continue
            interval_s = _coerce_interval(
                config.get("poll_interval_seconds") if config else default_interval_s
            )
            if hw.telemetry_last_polled is not None:
                age_s = (now - hw.telemetry_last_polled).total_seconds()
                if age_s < interval_s:
                    continue
            devices.append(
                {
                    "id": hw.id,
                    "profile": config.get("profile") if config else None,
                    "telemetry_config": config,
                    "host": config.get("host") if config else None,
                }
            )
    return devices


async def _poll_one(
    device: dict[str, Any],
    *,
    timeout_s: int,
) -> tuple[int, str, dict[str, Any]]:
    hw_stub = SimpleNamespace(id=device["id"], telemetry_config=device["telemetry_config"])
    source = str(device.get("profile") or "collector")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(poll_hardware, hw_stub, get_vault()),
            timeout=timeout_s,
        )
        if not isinstance(result, dict):
            result = {
                "status": "unknown",
                "error_msg": "Collector returned invalid payload",
                "data": {},
            }
        if "status" not in result:
            result["status"] = "unknown"
        return int(device["id"]), source, result
    except TimeoutError:
        return (
            int(device["id"]),
            source,
            {
                "status": "unreachable",
                "error_msg": f"Timeout reaching {device.get('host') or 'device'}",
                "data": {},
            },
        )
    except Exception as exc:  # noqa: BLE001
        return (
            int(device["id"]),
            source,
            {
                "status": "error",
                "error_msg": str(exc),
                "data": {},
            },
        )


async def collect_once(
    *,
    interval_s: int,
    timeout_s: int,
    max_parallel: int,
) -> None:
    devices = _discover_devices(interval_s)
    if not devices:
        logger.debug("Telemetry collector: no telemetry-enabled hardware due for poll.")
        return

    sem = asyncio.Semaphore(max_parallel)

    async def _run(device: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
        async with sem:
            return await _poll_one(device, timeout_s=timeout_s)

    results = await asyncio.gather(*[_run(d) for d in devices], return_exceptions=True)

    with get_session_context() as db:
        for item in results:
            if isinstance(item, BaseException):
                logger.warning("Telemetry collector task failed unexpectedly: %s", item)
                continue
            hardware_id, source, payload = item
            try:
                await write_telemetry(
                    hardware_id=hardware_id,
                    payload=payload,
                    source=source,
                    db=db,
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("Telemetry write failed for hardware %d: %s", hardware_id, exc)


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    _init_vault()

    interval_s = max(10, int(os.environ.get("CB_TELEMETRY_POLL_SECONDS", "30")))
    timeout_s = max(5, int(os.environ.get("CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS", "20")))
    max_parallel = max(1, int(os.environ.get("CB_TELEMETRY_MAX_PARALLEL", "8")))

    logger.info(
        "Telemetry collector started (interval=%ss timeout=%ss max_parallel=%s).",
        interval_s,
        timeout_s,
        max_parallel,
    )

    while not (shutdown_event and shutdown_event.is_set()):
        started = time.monotonic()
        try:
            await collect_once(
                interval_s=interval_s, timeout_s=timeout_s, max_parallel=max_parallel
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Telemetry collector loop failure: %s", exc, exc_info=True)

        elapsed = time.monotonic() - started
        sleep_s = max(1.0, interval_s - elapsed)
        if shutdown_event is None:
            await asyncio.sleep(sleep_s)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_s)
        except TimeoutError:
            pass

    logger.info("Telemetry collector stopped.")

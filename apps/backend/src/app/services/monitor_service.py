"""Uptime monitoring service.

Probe cascade (tried in order, host considered "up" if ANY succeeds):
  1. ICMP ping   — ping3 library with subprocess /bin/ping fallback
  2. TCP connect — socket.connect_ex on known open ports from last scan
  3. HTTP HEAD   — httpx.head on common web ports (80, 443, 8080, 8443)
  4. SNMP        — single sysUpTime GET (only when snmp_community is set)
"""

import json
import logging
import os
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow_iso
from app.core.validation import validate_snmp_community
from app.db.models import Hardware, HardwareMonitor, ScanResult, UptimeEvent

logger = logging.getLogger(__name__)

_HTTP_PROBE_PORTS = [80, 443, 8080, 8443]
_TCP_FALLBACK_PORTS = [22, 80, 443, 8080]

# When False, HTTP probe skips TLS verification (insecure; homelab self-signed only).
_VERIFY_TLS = os.environ.get("CB_MONITOR_VERIFY_TLS", "true").lower() in ("1", "true", "yes")
_TLS_WARNING_LOGGED = False


# ── Probe methods ─────────────────────────────────────────────────────────────


def probe_icmp(ip: str, timeout: float = 1.5) -> tuple[bool, float | None]:
    """ICMP ping. Returns (reachable, latency_ms)."""
    try:
        import ping3  # optional dep

        t0 = time.monotonic()
        result = ping3.ping(ip, timeout=timeout, unit="ms")
        if result is not None and result is not False:
            return True, result
    except Exception as exc:
        logger.debug("ping3 failed for %s: %s", ip, exc)

    try:
        t0 = time.monotonic()
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        latency = (time.monotonic() - t0) * 1000
        if r.returncode == 0:
            return True, round(latency, 2)
    except Exception as exc:
        logger.debug("subprocess ping failed for %s: %s", ip, exc)

    return False, None


def probe_tcp(ip: str, ports: list[int], timeout: float = 1.0) -> tuple[bool, float | None]:
    """TCP connect scan on given ports. Returns (reachable, latency_ms)."""
    for port in ports:
        try:
            t0 = time.monotonic()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            if s.connect_ex((ip, port)) == 0:
                latency = (time.monotonic() - t0) * 1000
                s.close()
                return True, round(latency, 2)
            s.close()
        except OSError:
            pass
    return False, None


def probe_http(
    ip: str, ports: list[int] | None = None, timeout: float = 2.0
) -> tuple[bool, float | None]:
    """HTTP HEAD probe. Returns (reachable, latency_ms)."""
    if ports is None:
        ports = _HTTP_PROBE_PORTS
    try:
        import httpx
    except ImportError:
        return False, None

    for port in ports:
        scheme = "https" if port in (443, 8443) else "http"
        url = f"{scheme}://{ip}:{port}/"
        try:
            t0 = time.monotonic()
            verify_tls = _VERIFY_TLS
            if not verify_tls:
                global _TLS_WARNING_LOGGED
                if not _TLS_WARNING_LOGGED:
                    _TLS_WARNING_LOGGED = True
                    logger.warning(
                        "CB_MONITOR_VERIFY_TLS=false: TLS verification disabled for monitor"
                        " HTTP probe (insecure; homelab self-signed only)"
                    )
            with httpx.Client(verify=verify_tls, timeout=timeout) as client:
                resp = client.head(url)
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code < 600:
                return True, round(latency, 2)
        except Exception:
            pass
    return False, None


def probe_snmp(
    ip: str, community: str = "public", timeout: float = 2.0
) -> tuple[bool, float | None]:
    """SNMP sysUpTime GET. Returns (reachable, latency_ms)."""
    try:
        community = validate_snmp_community(community)
    except ValueError:
        return False, None
    try:
        from pysnmp.hlapi import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            getCmd,
        )

        t0 = time.monotonic()
        error_indication, error_status, _, _var_binds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ip, 161), timeout=timeout, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.3.0")),  # sysUpTime
            )
        )
        latency = (time.monotonic() - t0) * 1000
        if not error_indication and not error_status:
            return True, round(latency, 2)
    except Exception:
        pass
    return False, None


# ── Core check logic ──────────────────────────────────────────────────────────


def check_host(
    ip: str,
    methods: list[str],
    tcp_ports: list[int] | None = None,
    snmp_community: str | None = None,
) -> tuple[str, float | None, str]:
    """Run probe cascade. Returns (status, latency_ms, method_used).

    Tries each method in `methods` order; stops on first success.
    Returns ("up", latency, method) or ("down", None, last_method_tried).
    """
    last_method = methods[0] if methods else "icmp"

    for method in methods:
        last_method = method
        if method == "icmp":
            ok, latency = probe_icmp(ip)
            if ok:
                return "up", latency, "icmp"

        elif method == "tcp":
            ports = tcp_ports or _TCP_FALLBACK_PORTS
            ok, latency = probe_tcp(ip, ports)
            if ok:
                return "up", latency, "tcp"

        elif method == "http":
            ok, latency = probe_http(ip)
            if ok:
                return "up", latency, "http"

        elif method == "snmp" and snmp_community:
            ok, latency = probe_snmp(ip, snmp_community)
            if ok:
                return "up", latency, "snmp"

    return "down", None, last_method


# ── Per-monitor runner ────────────────────────────────────────────────────────


def _get_tcp_ports_for_hardware(db: Session, hardware_id: int) -> list[int]:
    """Return open ports from the most recent accepted scan result for this hardware."""
    result = (
        db.query(ScanResult)
        .filter(
            ScanResult.matched_entity_id == hardware_id,
            ScanResult.matched_entity_type == "hardware",
            ScanResult.open_ports_json.isnot(None),
        )
        .order_by(ScanResult.id.desc())
        .first()
    )
    if result and result.open_ports_json:
        try:
            ports = result.open_ports_json
            if ports and isinstance(ports, list) and isinstance(ports[0], dict):
                return [p["port"] for p in ports if "port" in p]
            return [int(p) for p in ports]
        except Exception:
            pass
    return _TCP_FALLBACK_PORTS


def run_monitor(db: Session, monitor: HardwareMonitor) -> None:
    """Execute probe cascade for one monitor, persist results."""
    hw = db.get(Hardware, monitor.hardware_id)
    if not hw or not hw.ip_address:
        return

    methods = monitor.probe_methods if monitor.probe_methods else ["icmp", "tcp", "http"]
    tcp_ports = _get_tcp_ports_for_hardware(db, monitor.hardware_id)

    snmp_community = None
    try:
        from app.services.settings_service import get_or_create_settings

        settings = get_or_create_settings(db)
        snmp_community = settings.discovery_snmp_community or None
    except Exception:
        pass

    status, latency, method_used = check_host(
        hw.ip_address, methods, tcp_ports=tcp_ports, snmp_community=snmp_community
    )

    now = utcnow_iso()

    # NATS Telemetry Publisher
    try:
        import asyncio

        from app.core.nats_client import get_nc

        nc = get_nc()
        if nc and nc.is_connected:
            payload = {
                "hardware_id": monitor.hardware_id,
                "status": status,
                "latency_ms": latency,
                "probe_method": method_used,
                "checked_at": now,
            }
            # Fire and forget publishing to NATS
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    nc.publish(f"telemetry.raw.{monitor.hardware_id}", json.dumps(payload).encode())
                )
            except RuntimeError:
                # No running loop (e.g., synchronous thread)
                pass
    except Exception as exc:
        logger.debug("Failed to publish telemetry to NATS: %s", exc)

    # Write event to history ONLY if status changed or it's a daily heartbeat
    # For daily heartbeat, checking if last_checked_at is older than 24h
    write_event = False
    if monitor.last_status != status:
        write_event = True
    elif monitor.last_checked_at:
        try:
            last_dt = datetime.fromisoformat(monitor.last_checked_at.replace("Z", "+00:00"))
            if datetime.now(UTC) - last_dt > timedelta(hours=24):
                write_event = True
        except ValueError:
            write_event = True  # bad format, write just in case
    else:
        write_event = True

    if write_event:
        event = UptimeEvent(
            hardware_id=monitor.hardware_id,
            status=status,
            latency_ms=latency,
            probe_method=method_used,
            checked_at=now,
        )
        db.add(event)

    # Update monitor state
    if status == "up":
        monitor.consecutive_failures = 0
    else:
        monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1

    monitor.last_status = status
    monitor.last_checked_at = now
    monitor.latency_ms = latency
    monitor.updated_at = now

    # Propagate to Hardware.status and last_seen
    hw.status = "online" if status == "up" else "offline"
    if status == "up":
        hw.last_seen = now

    # Compute 24h uptime percentage from daily rollups (last 2 days to cover 24h rolling)
    try:
        from app.db.models import DailyUptimeStats

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        yesterday_str = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

        stats = db.scalars(
            select(DailyUptimeStats).where(
                DailyUptimeStats.hardware_id == monitor.hardware_id,
                DailyUptimeStats.date.in_([today_str, yesterday_str]),
            )
        ).all()

        total_mins = sum(s.total_minutes for s in stats)
        up_mins = sum(s.uptime_minutes for s in stats)

        # If we have daily stats, use them
        if total_mins > 0:
            monitor.uptime_pct_24h = round((up_mins / total_mins) * 100, 1)
        else:
            # Fallback for new monitors without rollups yet
            monitor.uptime_pct_24h = 100.0 if status == "up" else 0.0

    except Exception as exc:
        logger.debug("Failed to calculate 24h uptime from rollups: %s", exc)

    # Prune events older than 7 days to keep the table tidy
    prune_cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    db.query(UptimeEvent).filter(
        UptimeEvent.hardware_id == monitor.hardware_id,
        UptimeEvent.checked_at < prune_cutoff,
    ).delete()

    db.commit()


# ── Batch runner (APScheduler entry point) ────────────────────────────────────


def run_all_monitors(db: Session) -> None:
    """Poll all enabled monitors. Called by the APScheduler job."""
    monitors = db.scalars(select(HardwareMonitor).where(HardwareMonitor.enabled.is_(True))).all()
    for monitor in monitors:
        try:
            run_monitor(db, monitor)
        except Exception as exc:
            db.rollback()
            logger.warning("Monitor check failed for hardware_id=%s: %s", monitor.hardware_id, exc)


def run_all_monitors_job() -> None:
    """APScheduler-compatible wrapper — opens its own DB session."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        run_all_monitors(db)
    except Exception as exc:
        db.rollback()
        logger.error("run_all_monitors_job failed: %s", exc)
        raise
    finally:
        db.close()


# ── CRUD helpers ──────────────────────────────────────────────────────────────


def get_monitor(db: Session, hardware_id: int) -> HardwareMonitor | None:
    return db.scalar(select(HardwareMonitor).where(HardwareMonitor.hardware_id == hardware_id))


def create_monitor(
    db: Session,
    hardware_id: int,
    probe_methods: list[str] | None = None,
    interval_secs: int = 60,
    enabled: bool = True,
) -> HardwareMonitor:
    now = utcnow_iso()
    monitor = HardwareMonitor(
        hardware_id=hardware_id,
        enabled=enabled,
        interval_secs=interval_secs,
        probe_methods=probe_methods or ["icmp", "tcp", "http"],
        last_status="unknown",
        consecutive_failures=0,
        created_at=now,
        updated_at=now,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def update_monitor(
    db: Session,
    hardware_id: int,
    *,
    enabled: bool | None = None,
    interval_secs: int | None = None,
    probe_methods: list[str] | None = None,
) -> HardwareMonitor | None:
    monitor = get_monitor(db, hardware_id)
    if not monitor:
        return None
    if enabled is not None:
        monitor.enabled = enabled
    if interval_secs is not None:
        monitor.interval_secs = interval_secs
    if probe_methods is not None:
        monitor.probe_methods = probe_methods
    monitor.updated_at = utcnow_iso()
    db.commit()
    db.refresh(monitor)
    return monitor


def delete_monitor(db: Session, hardware_id: int) -> bool:
    monitor = get_monitor(db, hardware_id)
    if not monitor:
        return False
    db.delete(monitor)
    db.commit()
    return True


def get_history(db: Session, hardware_id: int, limit: int = 100) -> list[UptimeEvent]:
    return list(
        db.scalars(
            select(UptimeEvent)
            .where(UptimeEvent.hardware_id == hardware_id)
            .order_by(UptimeEvent.checked_at.desc())
            .limit(limit)
        ).all()
    )

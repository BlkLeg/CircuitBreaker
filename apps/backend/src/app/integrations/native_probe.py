"""Native (built-in) probe plugin — ICMP, HTTP, TCP checks for CB entities."""

from __future__ import annotations

import logging
import socket
import subprocess
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.egress import PRIVATE_LAN_HTTP, httpx_get
from app.core.url_validation import (
    MONITOR_TARGET_POLICY,
    validate_outbound_url,
    validate_redirect_target,
)
from app.db.models import IntegrationMonitor
from app.integrations.base import ConfigField, IntegrationPlugin, MonitorStatus
from app.services.ip_reservation import _parse_ports_json

_logger = logging.getLogger(__name__)

# Matches the monitor collector beside this one; a probe that needs more hops
# than this is a redirect loop, not a health check.
_MAX_PROBE_REDIRECTS = 20


class NativeProbePlugin(IntegrationPlugin):
    """Probe CB-managed hardware and services directly (no external monitoring tool needed).

    sync() queries all IntegrationMonitor rows for this integration that have
    a probe_type set, runs the appropriate network check, and returns MonitorStatus
    objects so the generic _upsert_monitors() worker handles DB writes.
    """

    TYPE = "native"
    DISPLAY_NAME = "Built-in Monitors"
    CONFIG_FIELDS: list[ConfigField] = []  # no credentials needed

    def test_connection(self, config: Any) -> tuple[bool, str]:
        return True, "Native monitors are always available"

    def sync(self, config: Any, **kwargs: Any) -> list[MonitorStatus]:
        """Probe all monitors registered under this integration.

        Two call sites use this plugin with different `config` shapes:
        integration_worker._sync_one passes a plain dict (base_url/slug/api_key,
        no id) plus an `integration_id` keyword argument; integration_sync_worker
        passes the Integration ORM row directly. Accept either.
        """
        db: Session | None = kwargs.get("db")
        if db is None:
            _logger.error("NativeProbePlugin.sync() called without db — skipping")
            return []

        integration_id: int | None = kwargs.get("integration_id")
        if integration_id is None:
            integration_id = getattr(config, "id", None)
        if integration_id is None:
            _logger.error("NativeProbePlugin.sync() could not determine integration_id — skipping")
            return []

        monitors = (
            db.query(IntegrationMonitor)
            .filter(
                IntegrationMonitor.integration_id == integration_id,
                IntegrationMonitor.probe_type.isnot(None),
            )
            .all()
        )

        results: list[MonitorStatus] = []
        for mon in monitors:
            try:
                status, latency_ms = _probe(mon)
            except Exception:
                _logger.exception("Probe failed for monitor %d (%s)", mon.id, mon.name)
                status, latency_ms = "down", None

            results.append(
                MonitorStatus(
                    external_id=mon.external_id,
                    name=mon.name,
                    url=mon.probe_target or mon.url,
                    status=status,
                    avg_response_ms=latency_ms,
                )
            )

        return results


# ── Probe dispatch ─────────────────────────────────────────────────────────────


def _probe(mon: IntegrationMonitor) -> tuple[str, float | None]:
    """Dispatch to the correct probe function based on probe_type."""
    probe_type = (mon.probe_type or "icmp").lower()
    target = mon.probe_target or ""
    if not target:
        return "down", None

    if probe_type == "http":
        return _probe_http(target)
    if probe_type == "tcp":
        port = mon.probe_port or 80
        return _probe_tcp(target, port)
    # Default: icmp
    return _probe_icmp(target)


def _probe_http(target: str, timeout: int = 5) -> tuple[str, float | None]:
    """HTTP probe — "up" if response status < 400.

    `probe_target` is operator-supplied and stored unvalidated, and this runs on
    a schedule, so it is validated on every probe rather than only at save time
    — the same reasoning `collectors/web.py` records for the monitor path beside
    it, plus the rows that predate any validation at all.

    Validation is also where air-gap enforcement lives for this call.
    `httpx_get` only runs `enforce_before_resolution`, which is deliberately a
    no-op for `PRIVATE_LAN_HTTP`; the resolved-answer check that actually
    refuses a public address under `CB_AIRGAP=true` is inside
    `validate_outbound_url`. Calling the client without it meant a scheduled
    probe of any external URL left an air-gapped install every interval, and
    reported "down" while it did.

    Redirects are followed by hand so every hop is re-validated. Leaving that to
    httpx let an allowed LAN target bounce the probe onward to link-local and
    the metadata address, which is the SSRF half of the same defect.
    """
    t0 = time.monotonic()
    try:
        validate_outbound_url(target, MONITOR_TARGET_POLICY)
        resp = httpx_get(target, policy=PRIVATE_LAN_HTTP, timeout=timeout, follow_redirects=False)
        hops = 0
        while resp.is_redirect and hops < _MAX_PROBE_REDIRECTS:
            hop = validate_redirect_target(
                str(resp.request.url),
                resp.headers.get("location", ""),
                MONITOR_TARGET_POLICY,
            )
            resp = httpx_get(
                hop.url, policy=PRIVATE_LAN_HTTP, timeout=timeout, follow_redirects=False
            )
            hops += 1
        latency_ms = (time.monotonic() - t0) * 1000
        status = "up" if resp.status_code < 400 else "down"
        return status, round(latency_ms, 2)
    except (ValueError, ConnectionError) as exc:
        # Refused, not unreachable. "down" alone cannot tell an operator whether
        # the host is switched off or the server declined to make the request, so
        # the refusal is logged where the silent version left no trace at all.
        _logger.warning("[native_probe] refused HTTP probe of %s: %s", target, exc)
        return "down", None
    except Exception as exc:  # noqa: BLE001 — a probe reports down; it never breaks the loop
        _logger.debug("[native_probe] HTTP probe failed for %s: %s", target, exc)
        return "down", None


def _probe_tcp(host: str, port: int, timeout: int = 5) -> tuple[str, float | None]:
    """TCP connect probe — "up" if connection succeeds."""
    t0 = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        latency_ms = (time.monotonic() - t0) * 1000
        if result == 0:
            return "up", round(latency_ms, 2)
        return "down", None
    except Exception as exc:
        _logger.debug("TCP probe failed for %s:%d: %s", host, port, exc)
        return "down", None


def _probe_icmp(host: str, timeout: int = 3) -> tuple[str, float | None]:
    """ICMP ping probe — falls back to TCP:80 if ping is blocked/unavailable."""
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True,
            timeout=timeout + 2,
        )
        latency_ms = (time.monotonic() - t0) * 1000
        if result.returncode == 0:
            return "up", round(latency_ms, 2)
        # ping returned non-zero — host unreachable
        return "down", None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # ping unavailable or timed out — fall back to TCP:80
        _logger.debug("ICMP ping unavailable for %s, falling back to TCP:80", host)
        return _probe_tcp(host, 80, timeout=timeout)
    except Exception as exc:
        _logger.debug("ICMP probe error for %s: %s", host, exc)
        return "down", None


# ── Probe target derivation ────────────────────────────────────────────────────


def derive_probe_config(
    hardware: Any | None = None,
    service: Any | None = None,
) -> tuple[str, str | None, int | None]:
    """Return (probe_type, probe_target, probe_port) from a hardware or service entity.

    Used both at API create time and in the discovery auto-pipeline.
    """
    if service is not None:
        if service.url:
            return "http", service.url, None
        if service.ip_address:
            port: int | None = None
            try:
                ports = _parse_ports_json(service.ports_json)
                if ports:
                    port = int(ports[0].get("port", 80))
            except Exception:
                pass
            return "tcp", service.ip_address, port
        return "icmp", service.ip_address, None

    if hardware is not None:
        target = hardware.hostname or hardware.ip_address
        return "icmp", target, None

    return "icmp", None, None

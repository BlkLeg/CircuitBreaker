"""Socket.IO client wrapper for Uptime Kuma 2.0 authenticated API.

Uses uptime-kuma-api-v2 (sync library) to fetch richer monitor data:
heartbeat history, response times, cert expiry.

Only compatible with Uptime Kuma 2.0.0-beta.2.
Falls back gracefully — callers should catch UptimeKumaSocketError.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from uptime_kuma_api import UptimeKumaApi

_logger = logging.getLogger(__name__)

_HEARTBEAT_HOURS = 2  # fetch last N hours of heartbeats per monitor
_STATUS_MAP = {1: "up", 0: "down", 2: "pending", 3: "maintenance"}


class UptimeKumaSocketError(Exception):
    """Raised when Socket.IO sync fails (caller should fall back to public API)."""


@dataclass
class HeartbeatData:
    timestamp: datetime
    status: str  # "up" | "down" | "pending" | "maintenance"
    response_ms: float | None


@dataclass
class RichMonitorData:
    external_id: str
    name: str
    url: str | None
    status: str
    avg_response_ms: float | None
    cert_expiry_days: int | None
    uptime_7d: float | None
    uptime_30d: float | None
    heartbeats: list[HeartbeatData] = field(default_factory=list)


def sync_rich(base_url: str, api_token: str) -> list[RichMonitorData]:
    """Connect via Socket.IO, fetch all active monitors and recent heartbeats.

    Raises UptimeKumaSocketError on any connection or auth failure so the
    caller can fall back to the public HTTP API.
    """
    try:
        with UptimeKumaApi(base_url) as api:
            api.login_by_token(api_token)
            raw_monitors: list[dict] = api.get_monitors()
            result: list[RichMonitorData] = []

            for mon in raw_monitors:
                if not mon.get("active", True):
                    continue  # skip paused/inactive monitors

                mid = mon["id"]
                status_code = mon.get("status", 2)
                status = _STATUS_MAP.get(status_code, "pending")

                cert_info = mon.get("certInfo") or {}
                cert_days: int | None = None
                raw_cert = cert_info.get("daysRemaining")
                if raw_cert is not None:
                    try:
                        cert_days = int(raw_cert)
                    except (TypeError, ValueError):
                        pass

                avg_ping = mon.get("avgPing")
                avg_ms: float | None = float(avg_ping) if avg_ping is not None else None

                try:
                    raw_beats = api.get_monitor_beats(mid, _HEARTBEAT_HOURS)
                except Exception as beat_exc:
                    _logger.warning(
                        "UK: failed to fetch heartbeats for monitor %s: %s", mid, beat_exc
                    )
                    raw_beats = []

                heartbeats: list[HeartbeatData] = []
                for hb in raw_beats:
                    ts_raw = hb.get("time")
                    if not ts_raw:
                        continue
                    try:
                        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                    ping = hb.get("ping")
                    heartbeats.append(
                        HeartbeatData(
                            timestamp=ts,
                            status=_STATUS_MAP.get(hb.get("status", 2), "pending"),
                            response_ms=float(ping) if ping is not None else None,
                        )
                    )

                result.append(
                    RichMonitorData(
                        external_id=str(mid),
                        name=mon.get("name", str(mid)),
                        url=mon.get("url"),
                        status=status,
                        avg_response_ms=avg_ms,
                        cert_expiry_days=cert_days,
                        uptime_7d=None,  # populated by caller from existing uptime dict
                        uptime_30d=None,  # populated by caller from existing uptime dict
                        heartbeats=heartbeats,
                    )
                )
            return result

    except Exception as exc:
        raise UptimeKumaSocketError(str(exc)) from exc

"""Uptime Kuma integration: dual-mode sync (Socket.IO + public HTTP fallback)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HardwareLiveMetric, IntegrationMonitor
from app.integrations.base import ConfigField, IntegrationPlugin, MonitorStatus

# Imported at module level so tests can patch app.integrations.uptime_kuma.sync_rich
# and app.integrations.uptime_kuma.get_vault.
try:
    from app.integrations.uptime_kuma_socket import sync_rich
except Exception:  # library not installed in all environments
    sync_rich = None  # type: ignore[assignment]

try:
    from app.services.credential_vault import get_vault
except ImportError:
    get_vault = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)

_STATUS_MAP = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}
_INACTIVE = {4, 5}  # inactive / paused codes


class UptimeKumaPlugin(IntegrationPlugin):
    """Sync monitors from Uptime Kuma.

    Uses Socket.IO (uptime-kuma-api-v2) when api_key is present;
    falls back to unauthenticated public Status Page API otherwise.
    """

    TYPE = "uptime_kuma"
    DISPLAY_NAME = "Uptime Kuma"
    CONFIG_FIELDS = [
        ConfigField(
            name="base_url",
            label="Base URL",
            type="url",
            required=True,
            placeholder="http://uptime-kuma:3001",
        ),
        ConfigField(
            name="slug",
            label="Status Page Slug",
            type="text",
            required=False,
            placeholder="default",
        ),
        ConfigField(
            name="api_key",
            label="API Token",
            type="password",
            required=False,
            secret=True,
            placeholder="(optional — enables richer sync)",
        ),
    ]

    # ── Public entry point ─────────────────────────────────────────────────

    def sync(self, config: Any, **kwargs: Any) -> list[MonitorStatus]:
        """Dual-mode sync. Decrypts api_key if present, tries Socket.IO first."""
        db: Session | None = kwargs.get("db")
        api_token: str | None = None
        if getattr(config, "api_key", None):
            try:
                if get_vault is None:
                    raise RuntimeError("credential_vault not available")
                api_token = get_vault().decrypt(config.api_key)
            except Exception:
                _logger.warning("UK: could not decrypt api_key — using public API")

        if api_token:
            try:
                return self._sync_socket(config, api_token, db)
            except Exception as exc:
                _logger.warning("UK Socket.IO sync failed (%s) — falling back to public API", exc)

        return self._sync_public(config)

    # ── Socket.IO path ─────────────────────────────────────────────────────

    def _sync_socket(self, config: Any, api_token: str, db: Session | None) -> list[MonitorStatus]:
        if sync_rich is None:
            raise RuntimeError("uptime_kuma_socket not available")

        rich_monitors = sync_rich(config.base_url, api_token)
        results: list[MonitorStatus] = []

        for rich in rich_monitors:
            results.append(
                MonitorStatus(
                    external_id=rich.external_id,
                    name=rich.name,
                    url=rich.url,
                    status=rich.status,
                    uptime_7d=rich.uptime_7d,
                    uptime_30d=rich.uptime_30d,
                )
            )

        if db is not None:
            self._apply_rich_data(db, rich_monitors)

        return results

    def _apply_rich_data(self, db: Session, rich_monitors: list[Any]) -> None:
        """Update monitor enrichment fields and write HardwareLiveMetric rows."""
        try:
            for rich in rich_monitors:
                mon = db.execute(
                    select(IntegrationMonitor).where(
                        IntegrationMonitor.external_id == rich.external_id
                    )
                ).scalar_one_or_none()
                if mon is None:
                    continue
                mon.avg_response_ms = rich.avg_response_ms
                mon.cert_expiry_days = rich.cert_expiry_days
                if rich.heartbeats:
                    mon.last_heartbeat_at = rich.heartbeats[-1].timestamp
                self._write_heartbeats(db, rich, mon)
            db.flush()
        except Exception as exc:
            _logger.error("UK: failed to apply rich monitor data: %s", exc)
            db.rollback()

    def _write_heartbeats(self, db: Session, rich: Any, mon: IntegrationMonitor) -> None:
        """Write heartbeat rows to HardwareLiveMetric for linked hardware assets."""
        if mon.linked_hardware_id is None or not rich.heartbeats:
            return

        # Fetch all existing timestamps in one query to avoid N×M round-trips
        hb_timestamps = [hb.timestamp for hb in rich.heartbeats]
        existing = set(
            db.execute(
                select(HardwareLiveMetric.collected_at).where(
                    HardwareLiveMetric.hardware_id == mon.linked_hardware_id,
                    HardwareLiveMetric.collected_at.in_(hb_timestamps),
                    HardwareLiveMetric.source == "uptime_kuma",
                )
            )
            .scalars()
            .all()
        )

        for hb in rich.heartbeats:
            if hb.timestamp in existing:
                continue
            db.add(
                HardwareLiveMetric(
                    hardware_id=mon.linked_hardware_id,
                    collected_at=hb.timestamp,
                    status=hb.status,
                    raw={"response_ms": hb.response_ms, "monitor_id": mon.external_id},
                    source="uptime_kuma",
                )
            )

    # ── Public HTTP fallback ───────────────────────────────────────────────

    def _status_page_url(self, config: Any) -> str:
        if isinstance(config, dict):
            base_url = config.get("base_url", "")
            slug = config.get("slug") or "default"
        else:
            base_url = config.base_url or ""
            slug = config.slug or "default"
        return f"{base_url.rstrip('/')}/api/status-page/{slug}"

    def _sync_public(self, config: Any) -> list[MonitorStatus]:
        """Read-only public Status Page API (no auth, UK 1.x + 2.x compatible)."""
        url = self._status_page_url(config)
        try:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            _logger.error("UK public sync failed: %s", exc)
            return []

        results: list[MonitorStatus] = []
        for group in data.get("publicGroupList", []):
            for mon in group.get("monitorList", []):
                status_code = mon.get("status", 2)
                if status_code in _INACTIVE:
                    continue
                uptime = mon.get("uptime", {})
                results.append(
                    MonitorStatus(
                        external_id=str(mon.get("id", "")),
                        name=mon.get("name", ""),
                        url=mon.get("url"),
                        status=_STATUS_MAP.get(status_code, "pending"),
                        uptime_7d=uptime.get("168"),
                        uptime_30d=uptime.get("720"),
                    )
                )
        return results

    # ── Connection test ────────────────────────────────────────────────────

    def test_connection(self, config: Any) -> tuple[bool, str]:
        """Validate connectivity (public API — no credentials required)."""
        url = self._status_page_url(config)
        try:
            resp = httpx.get(url, timeout=5)
            resp.raise_for_status()
            return True, "Connection successful"
        except Exception as exc:
            return False, str(exc)

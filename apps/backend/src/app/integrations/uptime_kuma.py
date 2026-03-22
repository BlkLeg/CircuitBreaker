"""Uptime Kuma integration plugin.

Uses the Uptime Kuma public Status Page API (v2 compatible):
  GET {base_url}/api/status-page/{slug}

No authentication required — data is from the public status page.
The user must create a Status Page in Uptime Kuma and add monitors to it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.base import ConfigField, IntegrationPlugin, MonitorStatus

_logger = logging.getLogger(__name__)

_STATUS_MAP = {
    0: "down",
    1: "up",
    2: "pending",
    3: "maintenance",
}

_REQUEST_TIMEOUT = 10.0


def _check_response(resp: httpx.Response, url: str = "") -> tuple[bool, str]:
    """Check response for empty body or non-JSON content before parsing."""
    _logger.debug(
        "Uptime Kuma response: url=%s status=%s content-type=%s body_preview=%r",
        url,
        resp.status_code,
        resp.headers.get("content-type", ""),
        resp.text[:120] if resp.text else "",
    )
    body = resp.text
    if not body or not body.strip():
        return False, (
            f"Empty response from server — verify base_url is correct (HTTP {resp.status_code})"
        )
    if "text/html" in resp.headers.get("content-type", ""):
        return False, (
            f"Got HTML response from {url} — verify base_url points to Uptime Kuma "
            "and the slug is correct"
        )
    return True, ""


def _extract_monitors(data: Any) -> tuple[bool, str, list]:
    """Extract flat monitor list from status page response.

    Returns (ok, error_message, monitors_list).
    """
    if not isinstance(data, dict):
        return False, "Unexpected response format", []

    if data.get("ok", True) is not True:
        msg = data.get("msg") or data.get("message") or "Uptime Kuma returned an error"
        return False, msg, []

    groups = data.get("publicGroupList", [])
    monitors = []
    for group in groups:
        monitors.extend(group.get("monitorList", []))

    return True, "", monitors


class UptimeKumaPlugin(IntegrationPlugin):
    TYPE = "uptime_kuma"
    DISPLAY_NAME = "Uptime Kuma"
    CONFIG_FIELDS = [
        ConfigField(
            name="base_url",
            label="Base URL",
            type="url",
            required=True,
            placeholder="http://uptime-kuma.example.com:3001",
        ),
        ConfigField(
            name="slug",
            label="Status Page Slug",
            type="text",
            required=True,
            placeholder="default",
        ),
    ]

    def _status_page_url(self, config: dict[str, Any]) -> str:
        base = config["base_url"].rstrip("/")
        slug = config.get("slug", "").strip("/")
        return f"{base}/api/status-page/{slug}"

    def test_connection(self, config: dict[str, Any]) -> tuple[bool, str]:
        try:
            url = self._status_page_url(config)
            with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
                resp = client.get(url)
            if not resp.is_success:
                return False, f"HTTP {resp.status_code}"
            ok, err = _check_response(resp, url)
            if not ok:
                return False, err
            data = resp.json()
            ok, err, monitors = _extract_monitors(data)
            if not ok:
                return False, err
            count = len(monitors)
            return True, f"{count} monitor{'s' if count != 1 else ''} found"
        except Exception as exc:
            _logger.debug("Uptime Kuma test_connection failed: %s", exc)
            return False, str(exc)

    def sync(self, config: dict[str, Any]) -> list[MonitorStatus]:
        try:
            url = self._status_page_url(config)
            with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
                resp = client.get(url)
            if not resp.is_success:
                _logger.warning("Uptime Kuma sync HTTP %s", resp.status_code)
                return []
            ok, err = _check_response(resp, url)
            if not ok:
                _logger.warning("Uptime Kuma sync: %s", err)
                return []
            data = resp.json()
            ok, err, monitors_raw = _extract_monitors(data)
            if not ok:
                _logger.warning("Uptime Kuma sync error: %s", err)
                return []

            results: list[MonitorStatus] = []
            for m in monitors_raw:
                try:
                    # Use top-level status field from status page response
                    raw_status = m.get("status", 1)
                    # active=0 means paused/disabled
                    if not m.get("active", 1):
                        status = "maintenance"
                    else:
                        status = _STATUS_MAP.get(raw_status, "pending")

                    uptime_dict = m.get("uptime") or {}
                    # Uptime Kuma returns uptime keyed by hour-count as strings
                    # "24"=24h, "720"=30d; approximate 7d from 168h key if present
                    uptime_7d = uptime_dict.get("168") or uptime_dict.get("24")
                    uptime_30d = uptime_dict.get("720")

                    results.append(
                        MonitorStatus(
                            external_id=str(m["id"]),
                            name=m.get("name", f"Monitor {m['id']}"),
                            url=m.get("url"),
                            status=status,
                            uptime_7d=float(uptime_7d) if uptime_7d is not None else None,
                            uptime_30d=float(uptime_30d) if uptime_30d is not None else None,
                        )
                    )
                except Exception as exc:
                    _logger.debug("Uptime Kuma: skipping malformed monitor: %s", exc)
                    continue

            return results
        except Exception as exc:
            _logger.warning("Uptime Kuma sync failed: %s", exc)
            return []

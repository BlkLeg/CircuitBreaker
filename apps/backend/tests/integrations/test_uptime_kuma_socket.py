"""Unit tests for uptime_kuma_socket — mock the uptime_kuma_api library."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.integrations.uptime_kuma_socket import (
    sync_rich,
)


def _make_monitor(id_=1, name="web", status=1, avg_response=120.0, cert_days=45):
    return {
        "id": id_,
        "name": name,
        "status": status,
        "url": "https://example.com",
        "active": True,
        "type": "http",
        "certInfo": {"daysRemaining": cert_days},
        "avgPing": avg_response,
    }


def _make_heartbeat(monitor_id=1, status=1, ping=120, time="2025-01-01T00:00:00Z"):
    return {
        "monitorID": monitor_id,
        "status": status,
        "ping": ping,
        "time": time,
        "important": True,
        "msg": "",
    }


@patch("app.integrations.uptime_kuma_socket.UptimeKumaApi")
def test_sync_rich_returns_monitors(mock_api_cls):
    mock_api = MagicMock()
    mock_api_cls.return_value.__enter__.return_value = mock_api
    mock_api.get_monitors.return_value = [_make_monitor(1, "web")]
    mock_api.get_monitor_beats.return_value = [_make_heartbeat(1)]

    result = sync_rich("http://uk.local:3001", "token123")

    assert len(result) == 1
    assert result[0].external_id == "1"
    assert result[0].name == "web"
    assert result[0].cert_expiry_days == 45
    assert len(result[0].heartbeats) == 1
    assert result[0].status == "up"


@patch("app.integrations.uptime_kuma_socket.UptimeKumaApi")
def test_sync_rich_heartbeat_status_mapped(mock_api_cls):
    mock_api = MagicMock()
    mock_api_cls.return_value.__enter__.return_value = mock_api
    mock_api.get_monitors.return_value = [_make_monitor(1)]
    mock_api.get_monitor_beats.return_value = [
        _make_heartbeat(1, status=1, ping=80),
        _make_heartbeat(1, status=0, ping=None),
    ]

    result = sync_rich("http://uk.local:3001", "token123")

    mock_api.login_by_token.assert_called_once_with("token123")
    hbs = result[0].heartbeats

    assert hbs[0].status == "up"
    assert hbs[0].response_ms == 80.0
    assert hbs[1].status == "down"
    assert hbs[1].response_ms is None


@patch("app.integrations.uptime_kuma_socket.UptimeKumaApi")
def test_sync_rich_inactive_monitors_excluded(mock_api_cls):
    mock_api = MagicMock()
    mock_api_cls.return_value.__enter__.return_value = mock_api
    mock_api.get_monitors.return_value = [
        _make_monitor(1, "active"),
        {**_make_monitor(2, "inactive"), "active": False},
    ]
    mock_api.get_monitor_beats.return_value = []

    result = sync_rich("http://uk.local:3001", "token")
    assert len(result) == 1
    assert result[0].external_id == "1"

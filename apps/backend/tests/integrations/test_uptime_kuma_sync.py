"""Tests for dual-mode sync: Socket.IO rich path and public API fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.db.models import HardwareLiveMetric, IntegrationMonitor
from app.integrations.uptime_kuma import UptimeKumaPlugin
from app.integrations.uptime_kuma_socket import (
    HeartbeatData,
    RichMonitorData,
    UptimeKumaSocketError,
)


def _make_rich_monitor(hw_id: int | None = None) -> tuple[RichMonitorData, IntegrationMonitor]:
    rich = RichMonitorData(
        external_id="42",
        name="test-svc",
        url="https://test.example.com",
        status="up",
        avg_response_ms=95.0,
        cert_expiry_days=60,
        uptime_7d=99.5,
        uptime_30d=98.0,
        heartbeats=[
            HeartbeatData(
                timestamp=datetime.now(tz=UTC) - timedelta(minutes=5),
                status="up",
                response_ms=90.0,
            ),
            HeartbeatData(
                timestamp=datetime.now(tz=UTC) - timedelta(minutes=1),
                status="down",
                response_ms=None,
            ),
        ],
    )
    mon = IntegrationMonitor(
        integration_id=1,
        external_id="42",
        name="test-svc",
        linked_hardware_id=hw_id,
    )
    return rich, mon


def test_write_heartbeats_linked_monitor(db_session, factories):
    """When monitor has linked_hardware_id, heartbeats become HardwareLiveMetric rows."""
    intg = factories.integration()
    hw = factories.hardware(name="ext-node", ip_address="10.20.0.1")
    rich, mon = _make_rich_monitor(hw_id=hw.id)
    mon.integration_id = intg.id
    db_session.add(mon)
    db_session.flush()

    plugin = UptimeKumaPlugin()
    plugin._write_heartbeats(db_session, rich, mon)
    db_session.flush()

    rows = (
        db_session.query(HardwareLiveMetric)
        .filter_by(hardware_id=hw.id, source="uptime_kuma")
        .all()
    )
    assert len(rows) == 2
    statuses = {r.status for r in rows}
    assert statuses == {"up", "down"}


def test_write_heartbeats_unlinked_monitor(db_session, factories):
    """Monitor without linked_hardware_id produces no HardwareLiveMetric rows."""
    intg = factories.integration()
    rich, mon = _make_rich_monitor(hw_id=None)
    mon.integration_id = intg.id
    db_session.add(mon)
    db_session.flush()

    plugin = UptimeKumaPlugin()
    plugin._write_heartbeats(db_session, rich, mon)
    db_session.flush()

    count = db_session.query(HardwareLiveMetric).filter_by(source="uptime_kuma").count()
    assert count == 0


@patch("app.integrations.uptime_kuma.sync_rich")
def test_fallback_to_public_api_on_socket_error(mock_sync_rich, db_session):
    """When Socket.IO raises UptimeKumaSocketError, falls back to public API."""
    mock_sync_rich.side_effect = UptimeKumaSocketError("connection refused")

    plugin = UptimeKumaPlugin()
    config = MagicMock()
    config.api_key = "encrypted_tok"
    config.base_url = "http://uk:3001"
    config.slug = "default"

    with (
        patch("app.integrations.uptime_kuma.get_vault") as mock_vault,
        patch.object(plugin, "_sync_public", return_value=[]) as mock_public,
    ):
        mock_vault.return_value.decrypt.return_value = "plaintext_token"
        result = plugin.sync(config, db=db_session)
        mock_public.assert_called_once()
        assert result == []  # mock_public returns []


def test_write_heartbeats_deduplicates(db_session, factories):
    """Calling _write_heartbeats twice with same data does not double-insert."""
    intg = factories.integration()
    hw = factories.hardware(name="dedup-node", ip_address="10.20.0.2")
    rich, mon = _make_rich_monitor(hw_id=hw.id)
    mon.integration_id = intg.id
    db_session.add(mon)
    db_session.flush()

    plugin = UptimeKumaPlugin()
    plugin._write_heartbeats(db_session, rich, mon)
    db_session.flush()
    plugin._write_heartbeats(db_session, rich, mon)
    db_session.flush()

    count = (
        db_session.query(HardwareLiveMetric)
        .filter_by(hardware_id=hw.id, source="uptime_kuma")
        .count()
    )
    assert count == 2  # same 2 rows, not 4

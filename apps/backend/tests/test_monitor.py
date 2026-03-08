import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import Hardware, HardwareMonitor, UptimeEvent
from app.services.monitor_service import run_monitor


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def monitor():
    m = HardwareMonitor(
        hardware_id=1,
        enabled=True,
        interval_secs=60,
        probe_methods=json.dumps(["icmp"]),
        last_status="unknown",
        last_checked_at=None,
        consecutive_failures=0,
    )
    return m


@pytest.fixture
def hardware():
    h = Hardware(id=1, ip_address="192.168.1.100", status="unknown")
    return h


@patch("app.services.monitor_service.check_host")
@patch("app.core.nats_client.get_nc")
def test_run_monitor_state_transition(mock_get_nc, mock_check_host, mock_db, monitor, hardware):
    # Setup
    mock_db.get.return_value = hardware
    mock_check_host.return_value = ("up", 1.5, "icmp")

    mock_nc = MagicMock()
    mock_nc.is_connected = True
    mock_get_nc.return_value = mock_nc

    # Run
    run_monitor(mock_db, monitor)

    # Verify NATS publish was called (or at least attempted via task)
    assert mock_get_nc.called

    # Verify DB write (transition from unknown -> up)
    assert mock_db.add.called
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, UptimeEvent)
    assert added_obj.status == "up"

    # reset mocks
    mock_db.add.reset_mock()

    # Now simulate another check where status is still "up"
    # To avoid daily heartbeat, set last_checked_at to now
    monitor.last_status = "up"
    monitor.last_checked_at = datetime.now(UTC).isoformat()
    mock_check_host.return_value = ("up", 1.2, "icmp")

    run_monitor(mock_db, monitor)

    # DB add should NOT be called since status didn't change
    mock_db.add.assert_not_called()

    # Now simulate a failure (transition up -> down)
    monitor.last_status = "up"
    mock_check_host.return_value = ("down", None, "icmp")

    run_monitor(mock_db, monitor)

    # DB add SHOULD be called
    assert mock_db.add.called
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, UptimeEvent)
    assert added_obj.status == "down"

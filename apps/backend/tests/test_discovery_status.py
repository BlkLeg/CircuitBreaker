"""Validation tests for discovery status computation (_compute_discovery_status)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from app.api.discovery import _compute_discovery_status
from app.db.models import AppSettings, ScanJob, ScanResult
from app.schemas.discovery import DiscoveryStatusOut


def test_compute_discovery_status_returns_correct_shape_and_values():
    settings = MagicMock(spec=AppSettings)
    settings.discovery_enabled = True
    settings.scan_ack_accepted = True
    settings.discovery_mode = "full"
    settings.docker_socket_path = "/var/run/docker.sock"

    pending_count = 2
    active_jobs_list = []
    last_completed_job = MagicMock(spec=ScanJob)
    last_completed_job.completed_at = "2025-01-15T12:00:00Z"

    db = MagicMock()

    call_count = [0]

    def _query(model):
        if model is ScanResult:
            q = MagicMock()
            q.filter.return_value.count.return_value = pending_count
            return q.filter.return_value
        if model is ScanJob:
            call_count[0] += 1
            q = MagicMock()
            if call_count[0] == 1:
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
                    active_jobs_list
                )
                return q.filter.return_value.order_by.return_value.limit.return_value
            q.filter.return_value.order_by.return_value.first.return_value = last_completed_job
            return q.filter.return_value.order_by.return_value
        raise AssertionError(f"unexpected model {model}")

    db.query.side_effect = _query

    next_run = datetime(2025, 1, 20, 3, 0, 0)
    mock_scheduler = MagicMock()
    mock_job = MagicMock()
    mock_job.id = "discovery_profile_1"
    mock_job.next_run_time = next_run
    mock_scheduler.get_jobs.return_value = [mock_job]

    with (
        patch("app.api.discovery.get_scheduler", return_value=mock_scheduler),
        patch("app.api.discovery.get_or_create_settings", return_value=settings),
        patch("app.api.discovery._has_raw_socket_privilege", return_value=True),
        patch("app.api.discovery.is_docker_socket_available", return_value=True),
        patch(
            "app.services.docker_discovery.get_docker_status", return_value={"container_count": 5}
        ),
    ):
        out = _compute_discovery_status(db)

    assert isinstance(out, DiscoveryStatusOut)
    assert out.discovery_enabled is True
    assert out.scan_ack_accepted is True
    assert out.pending_results == pending_count
    assert out.active_jobs == []
    assert out.last_scan == "2025-01-15T12:00:00Z"
    assert out.next_scheduled is not None
    assert "2025-01-20" in out.next_scheduled
    assert out.discovery_mode == "full"
    assert out.effective_mode == "full"
    assert out.net_raw_capable is True
    assert out.docker_available is True
    assert out.docker_container_count == 5


def test_compute_discovery_status_downgrades_to_safe_when_no_net_raw():
    settings = MagicMock(spec=AppSettings)
    settings.discovery_enabled = False
    settings.scan_ack_accepted = False
    settings.discovery_mode = "full"
    settings.docker_socket_path = "/var/run/docker.sock"

    db = MagicMock()
    scan_job_calls = [0]

    def _query(model):
        if model is ScanResult:
            q = MagicMock()
            q.filter.return_value.count.return_value = 0
            return q.filter.return_value
        if model is ScanJob:
            scan_job_calls[0] += 1
            q = MagicMock()
            if scan_job_calls[0] == 1:
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
                return q.filter.return_value.order_by.return_value.limit.return_value
            q.filter.return_value.order_by.return_value.first.return_value = None
            return q.filter.return_value.order_by.return_value
        raise AssertionError(f"unexpected model {model}")

    db.query.side_effect = _query

    mock_scheduler = MagicMock()
    mock_scheduler.get_jobs.return_value = []

    with (
        patch("app.api.discovery.get_scheduler", return_value=mock_scheduler),
        patch("app.api.discovery.get_or_create_settings", return_value=settings),
        patch("app.api.discovery._has_raw_socket_privilege", return_value=False),
        patch("app.api.discovery.is_docker_socket_available", return_value=False),
        patch(
            "app.services.docker_discovery.get_docker_status", return_value={"container_count": 0}
        ),
    ):
        out = _compute_discovery_status(db)

    assert out.discovery_mode == "full"
    assert out.effective_mode == "safe"
    assert out.net_raw_capable is False
    assert out.docker_available is False
    assert out.docker_container_count == 0
    assert out.pending_results == 0
    assert out.active_jobs == []
    assert out.last_scan is None
    assert out.next_scheduled is None

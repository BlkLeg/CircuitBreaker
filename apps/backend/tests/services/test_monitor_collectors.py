from unittest.mock import patch

from app.services.monitoring.collectors import (
    COLLECTORS,
    collect_http,
    collect_icmp,
    collect_tcp,
)


def _metric(samples, name):
    return next(s.value for s in samples if s.metric == name)


def test_icmp_all_replies_zero_loss():
    # 5 replies of 10,12,11,13,10 ms
    with patch(
        "app.services.monitoring.collectors._ping_once",
        side_effect=[10.0, 12.0, 11.0, 13.0, 10.0],
    ):
        samples = collect_icmp("10.0.0.5", {"packet_count": 5, "timeout": 1.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "packet_loss_pct") == 0.0
    assert _metric(samples, "latency_ms") == 11.2  # mean
    assert _metric(samples, "latency_min_ms") == 10.0
    assert _metric(samples, "latency_max_ms") == 13.0


def test_icmp_partial_loss():
    with patch(
        "app.services.monitoring.collectors._ping_once",
        side_effect=[10.0, None, 12.0, None, 14.0],
    ):
        samples = collect_icmp("10.0.0.5", {"packet_count": 5, "timeout": 1.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "packet_loss_pct") == 40.0
    assert _metric(samples, "latency_ms") == 12.0  # mean of replies only


def test_icmp_total_loss_is_down():
    with patch(
        "app.services.monitoring.collectors._ping_once",
        side_effect=[None, None, None],
    ):
        samples = collect_icmp("10.0.0.5", {"packet_count": 3, "timeout": 1.0})
    assert _metric(samples, "avail") == 0.0
    assert _metric(samples, "packet_loss_pct") == 100.0


def test_icmp_missing_tool_reports_error_reason():
    with patch(
        "app.services.monitoring.collectors._ping_once",
        side_effect=FileNotFoundError("ping"),
    ):
        samples = collect_icmp("10.0.0.5", {"packet_count": 3})
    avail = next(s for s in samples if s.metric == "avail")
    assert avail.value == 0.0
    assert avail.error_reason == "icmp_unavailable"


def test_tcp_up_when_any_port_connects():
    with patch(
        "app.services.monitoring.collectors._tcp_connect",
        side_effect=[(False, None), (True, 5.0)],
    ):
        samples = collect_tcp("10.0.0.5", {"ports": [22, 443], "timeout": 1.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "latency_ms") == 5.0


def test_http_status_class_recorded():
    with patch(
        "app.services.monitoring.collectors._http_head",
        return_value=(200, 8.0),
    ):
        samples = collect_http("10.0.0.5", {"url": "http://10.0.0.5/", "timeout": 2.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "http_status_class") == 2.0


def test_registry_maps_check_types():
    assert COLLECTORS["icmp"] is collect_icmp
    assert COLLECTORS["tcp"] is collect_tcp
    assert COLLECTORS["http"] is collect_http

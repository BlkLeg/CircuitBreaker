import subprocess
from types import SimpleNamespace

import pytest

from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample, net


def _metric(samples: list[Sample], name: str) -> float:
    return next(s.value for s in samples if s.metric == name)


def test_icmp_all_up(monkeypatch):
    monkeypatch.setattr(net, "_ping_once", lambda host, timeout: 12.5)
    result = net.collect_icmp("192.0.2.1", {"packet_count": 3})
    assert isinstance(result, CheckResult)
    assert result.up is True
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["packet_loss_pct"] == 0.0


def test_icmp_all_replies_zero_loss(monkeypatch):
    # 5 replies of 10,12,11,13,10 ms
    values = iter([10.0, 12.0, 11.0, 13.0, 10.0])
    monkeypatch.setattr(net, "_ping_once", lambda host, timeout: next(values))
    result = net.collect_icmp("10.0.0.5", {"packet_count": 5, "timeout": 1.0})
    assert result.up is True
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["packet_loss_pct"] == 0.0
    assert metrics["latency_ms"] == 11.2  # mean
    assert metrics["latency_min_ms"] == 10.0
    assert metrics["latency_max_ms"] == 13.0


def test_icmp_partial_loss(monkeypatch):
    values = iter([10.0, None, 12.0, None, 14.0])
    monkeypatch.setattr(net, "_ping_once", lambda host, timeout: next(values))
    result = net.collect_icmp("10.0.0.5", {"packet_count": 5, "timeout": 1.0})
    assert result.up is True
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["packet_loss_pct"] == 40.0
    assert metrics["latency_ms"] == 12.0  # mean of replies only


def test_icmp_all_lost(monkeypatch):
    monkeypatch.setattr(net, "_ping_once", lambda host, timeout: None)
    result = net.collect_icmp("192.0.2.1", {"packet_count": 3})
    assert result.up is False
    assert "loss" in result.msg
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 0.0
    assert metrics["packet_loss_pct"] == 100.0


def test_icmp_missing_tool_reports_error_reason(monkeypatch):
    def _raise(host, timeout):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(net, "_ping_once", _raise)
    result = net.collect_icmp("10.0.0.5", {"packet_count": 3})
    assert result.up is False
    avail = next(s for s in result.samples if s.metric == "avail")
    assert avail.value == 0.0
    assert avail.error_reason == "icmp_unavailable"


# ── _ping_once: raw-socket probe with a system-ping fallback ─────────────────


def _unavailable(*_args, **_kwargs):
    return net._PROBE_UNAVAILABLE


def test_ping_once_prefers_the_raw_socket_probe(monkeypatch):
    monkeypatch.setattr(net, "_raw_socket_ping", lambda host, timeout: 4.25)
    monkeypatch.setattr(net, "_system_ping", lambda host, timeout: pytest.fail("not reached"))
    assert net._ping_once("10.0.0.5", 1.0) == 4.25


def test_ping_once_reports_loss_from_the_raw_socket_probe(monkeypatch):
    monkeypatch.setattr(net, "_raw_socket_ping", lambda host, timeout: None)
    monkeypatch.setattr(net, "_system_ping", lambda host, timeout: pytest.fail("not reached"))
    assert net._ping_once("10.0.0.5", 1.0) is None


def test_ping_once_falls_back_to_the_system_ping_binary(monkeypatch):
    """Without CAP_NET_RAW (native installs, dev shells) ICMP must still work."""
    monkeypatch.setattr(net, "_raw_socket_ping", _unavailable)
    monkeypatch.setattr(net, "_system_ping", lambda host, timeout: 3.5)
    assert net._ping_once("10.0.0.5", 1.0) == 3.5


def test_ping_once_raises_when_no_probe_can_run(monkeypatch):
    monkeypatch.setattr(net, "_raw_socket_ping", _unavailable)
    monkeypatch.setattr(net, "_system_ping", _unavailable)
    with pytest.raises(OSError):
        net._ping_once("10.0.0.5", 1.0)


def test_system_ping_parses_the_rtt(monkeypatch):
    stdout = (
        "PING 10.0.0.5 (10.0.0.5) 56(84) bytes of data.\n"
        "64 bytes from 10.0.0.5: icmp_seq=1 ttl=64 time=3.43 ms\n"
    )
    monkeypatch.setattr(
        net.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    assert net._system_ping("10.0.0.5", 1.0) == 3.43


def test_system_ping_reports_loss_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        net.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert net._system_ping("10.0.0.5", 1.0) is None


def test_system_ping_reports_loss_on_timeout(monkeypatch):
    def _timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="ping", timeout=3)

    monkeypatch.setattr(net.subprocess, "run", _timeout)
    assert net._system_ping("10.0.0.5", 1.0) is None


def test_system_ping_unavailable_without_the_binary(monkeypatch):
    def _missing(*_a, **_kw):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(net.subprocess, "run", _missing)
    assert net._system_ping("10.0.0.5", 1.0) is net._PROBE_UNAVAILABLE


def test_system_ping_rejects_option_like_hosts(monkeypatch):
    monkeypatch.setattr(net.subprocess, "run", lambda *a, **kw: pytest.fail("must not spawn"))
    assert net._system_ping("-oProxyCommand=x", 1.0) is net._PROBE_UNAVAILABLE
    assert net._system_ping("host; rm -rf /", 1.0) is net._PROBE_UNAVAILABLE


def test_icmp_end_to_end_over_the_system_ping_fallback(monkeypatch):
    """The collector reports real latency when only the ping binary is available."""
    monkeypatch.setattr(net, "_raw_socket_ping", _unavailable)
    monkeypatch.setattr(net, "_system_ping", lambda host, timeout: 3.4)
    result = net.collect_icmp("192.168.0.4", {"packet_count": 2})
    assert result.up is True
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["latency_ms"] == 3.4
    assert metrics["packet_loss_pct"] == 0.0


def test_tcp_up_when_any_port_connects(monkeypatch):
    responses = iter([(False, None), (True, 5.0)])
    monkeypatch.setattr(net, "_tcp_connect", lambda h, p, t: next(responses))
    result = net.collect_tcp("10.0.0.5", {"ports": [22, 443], "timeout": 1.0})
    assert result.up is True
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["latency_ms"] == 5.0


def test_tcp_down(monkeypatch):
    monkeypatch.setattr(net, "_tcp_connect", lambda h, p, t: (False, None))
    result = net.collect_tcp("192.0.2.1", {"port": 22})
    assert result.up is False


def test_registry_keys():
    assert {"icmp", "tcp"} <= set(COLLECTORS)

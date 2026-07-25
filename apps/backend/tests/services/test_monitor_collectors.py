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

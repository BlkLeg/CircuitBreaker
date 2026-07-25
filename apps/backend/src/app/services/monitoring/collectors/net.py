"""ICMP and TCP reachability checks."""

from __future__ import annotations

import socket
import time

from app.services.monitoring.collectors import CheckResult, Sample, register

# ── Probe primitives (mocked in tests) ─────────────────────────────────────────


def _ping_once(host: str, timeout: float) -> float | None:
    """One ICMP echo. Returns latency in ms, or None on loss. Raises on missing tool."""
    import ping3  # optional dep; ImportError surfaces as a hard failure

    ping3.EXCEPTIONS = False
    result = ping3.ping(host, timeout=timeout, unit="ms")
    if result is None or result is False:
        return None
    return round(float(result), 3)


def _tcp_connect(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.monotonic() - t0) * 1000, 2)
    except OSError:
        return False, None


def _jitter(latencies: list[float]) -> float:
    if len(latencies) < 2:
        return 0.0
    deltas = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
    return round(sum(deltas) / len(deltas), 3)


# ── Collectors ─────────────────────────────────────────────────────────────────


def collect_icmp(host: str, params: dict) -> CheckResult:
    count = int(params.get("packet_count", 5))
    timeout = float(params.get("timeout", 1.5))
    latencies: list[float] = []
    lost = 0
    try:
        for _ in range(count):
            rtt = _ping_once(host, timeout)
            if rtt is None:
                lost += 1
            else:
                latencies.append(rtt)
    except (ImportError, FileNotFoundError, OSError):
        return CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="icmp_unavailable")],
            msg="icmp probe unavailable on this host",
        )

    loss_pct = round(lost / count * 100, 2) if count else 100.0
    up = bool(latencies)
    samples = [Sample("avail", 1.0 if up else 0.0), Sample("packet_loss_pct", loss_pct)]
    if latencies:
        mean = round(sum(latencies) / len(latencies), 3)
        samples += [
            Sample("latency_ms", mean),
            Sample("latency_min_ms", min(latencies)),
            Sample("latency_max_ms", max(latencies)),
            Sample("jitter_ms", _jitter(latencies)),
        ]
        msg = f"{mean}ms avg, {loss_pct}% loss"
    else:
        msg = f"100% packet loss ({count} probes)"
    return CheckResult(up=up, samples=samples, msg=msg)


def collect_tcp(host: str, params: dict) -> CheckResult:
    ports = params.get("ports") or [params.get("port", 80)]
    timeout = float(params.get("timeout", 1.0))
    for port in ports:
        ok, latency = _tcp_connect(host, int(port), timeout)
        if ok and latency is not None:
            return CheckResult(
                up=True,
                samples=[Sample("avail", 1.0), Sample("latency_ms", latency)],
                msg=f"port {port} open in {latency}ms",
            )
    return CheckResult(
        up=False,
        samples=[Sample("avail", 0.0)],
        msg=f"no reachable port in {ports}",
    )


register("icmp", collect_icmp)
register("tcp", collect_tcp)

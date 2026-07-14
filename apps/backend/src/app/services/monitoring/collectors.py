"""Pure collector functions for the polling engine.

Each collector runs blocking network I/O and returns a list of Samples. It must
NEVER raise for an unreachable host — it returns avail=0.0 (with error_reason on
a hard failure like a missing tool). No DB access here so collectors are unit-
testable by mocking the private probe helpers.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    metric: str
    value: float
    error_reason: str | None = None


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


def _http_head(url: str, timeout: float) -> tuple[int, float]:
    import httpx

    t0 = time.monotonic()
    resp = httpx.head(url, timeout=timeout, follow_redirects=True)
    return resp.status_code, round((time.monotonic() - t0) * 1000, 2)


# ── Collectors ─────────────────────────────────────────────────────────────────


def collect_icmp(host: str, params: dict) -> list[Sample]:
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
        return [Sample("avail", 0.0, error_reason="icmp_unavailable")]

    loss_pct = round(lost / count * 100, 2) if count else 100.0
    up = 1.0 if latencies else 0.0
    out = [Sample("avail", up), Sample("packet_loss_pct", loss_pct)]
    if latencies:
        mean = round(sum(latencies) / len(latencies), 3)
        jitter = _jitter(latencies)
        out += [
            Sample("latency_ms", mean),
            Sample("latency_min_ms", min(latencies)),
            Sample("latency_max_ms", max(latencies)),
            Sample("jitter_ms", jitter),
        ]
    return out


def _jitter(latencies: list[float]) -> float:
    if len(latencies) < 2:
        return 0.0
    deltas = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
    return round(sum(deltas) / len(deltas), 3)


def collect_tcp(host: str, params: dict) -> list[Sample]:
    ports = params.get("ports") or [params.get("port", 80)]
    timeout = float(params.get("timeout", 1.0))
    for port in ports:
        ok, latency = _tcp_connect(host, int(port), timeout)
        if ok and latency is not None:
            return [Sample("avail", 1.0), Sample("latency_ms", latency)]
    return [Sample("avail", 0.0)]


def collect_http(host: str, params: dict) -> list[Sample]:
    url = params.get("url") or f"http://{host}/"
    timeout = float(params.get("timeout", 2.0))
    try:
        status, latency = _http_head(url, timeout)
    except Exception:  # noqa: BLE001 — network failure is a datum, not an error
        return [Sample("avail", 0.0, error_reason="http_error")]
    return [
        Sample("avail", 1.0),
        Sample("latency_ms", latency),
        Sample("http_status_class", float(status // 100)),
    ]


COLLECTORS: dict[str, Callable[[str, dict], list[Sample]]] = {
    "icmp": collect_icmp,
    "tcp": collect_tcp,
    "http": collect_http,
}

"""ICMP and TCP reachability checks."""

from __future__ import annotations

import re
import socket
import subprocess
import time
from typing import Any

from app.services.monitoring.collectors import CheckResult, Sample, register

# ── Probe primitives (mocked in tests) ─────────────────────────────────────────

# Distinguishes "this probe cannot run here" from "the probe ran, the host was
# silent" (None) — only the latter counts as packet loss.
_PROBE_UNAVAILABLE: Any = object()

# Hosts are passed to the ping binary as argv, so shell metacharacters can't do
# anything; this keeps an option-looking host from being read as a flag.
_PINGABLE_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:%-]*$")
_PING_RTT = re.compile(r"time[=<]\s*([\d.]+)\s*ms")


def _raw_socket_ping(host: str, timeout: float) -> float | None | Any:
    """ICMP echo over a raw socket. Needs CAP_NET_RAW; ping3 is an optional dep."""
    try:
        import ping3
    except ImportError:
        return _PROBE_UNAVAILABLE
    ping3.EXCEPTIONS = False
    try:
        result = ping3.ping(host, timeout=timeout, unit="ms")
    except OSError:
        return _PROBE_UNAVAILABLE  # no raw-socket permission
    if result is None or result is False:
        return None
    return round(float(result), 3)


def _system_ping(host: str, timeout: float) -> float | None | Any:
    """ICMP echo via the system ping binary — setuid/cap_net_raw in most distros."""
    if not _PINGABLE_HOST.match(host):
        return _PROBE_UNAVAILABLE
    wait = max(1, round(timeout))
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ping", "-n", "-c", "1", "-W", str(wait), host],
            capture_output=True,
            text=True,
            timeout=wait + 2,
        )
    except subprocess.TimeoutExpired:
        return None  # host stayed silent past the deadline
    except (OSError, subprocess.SubprocessError):
        return _PROBE_UNAVAILABLE  # no ping binary on this host
    if proc.returncode != 0:
        return None
    match = _PING_RTT.search(proc.stdout)
    return round(float(match.group(1)), 3) if match else None


def _ping_once(host: str, timeout: float) -> float | None:
    """One ICMP echo. Returns latency in ms, or None on loss.

    Raw-socket ICMP needs CAP_NET_RAW, which the container workers have but
    native installs and dev shells often don't, so fall back to the system ping
    binary (same layering as services/discovery_safe.py). Raises OSError only
    when neither probe can run at all.
    """
    for probe in (_raw_socket_ping, _system_ping):
        result = probe(host, timeout)
        if result is not _PROBE_UNAVAILABLE:
            return result
    raise OSError(f"no ICMP probe available for {host}")


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
            msg="ICMP unavailable: no raw-socket permission and no ping binary",
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

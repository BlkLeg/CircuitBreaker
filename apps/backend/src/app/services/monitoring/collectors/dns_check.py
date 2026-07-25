"""DNS resolution check with optional expected-value matching."""

from __future__ import annotations

import time

from app.services.monitoring.collectors import CheckResult, Sample, register


class DnsLookupError(Exception):
    """Raised by _resolve on any lookup failure (wrapped for testability)."""


def _resolve(hostname: str, params: dict) -> tuple[list[str], float]:
    """Resolve one record set. Returns (record strings, latency_ms). Mocked in tests."""
    import dns.resolver

    resolver = dns.resolver.Resolver()
    if params.get("resolver"):
        resolver.nameservers = [str(params["resolver"])]
    resolver.port = int(params.get("port", 53))
    timeout = float(params.get("timeout", 5.0))
    resolver.timeout = timeout
    resolver.lifetime = timeout
    record_type = str(params.get("record_type", "A")).upper()
    t0 = time.monotonic()
    try:
        answer = resolver.resolve(hostname, record_type)
    except Exception as exc:  # noqa: BLE001 — normalized for the collector
        raise DnsLookupError(str(exc)) from exc
    latency = round((time.monotonic() - t0) * 1000, 2)
    return [str(r) for r in answer], latency


def collect_dns(host: str, params: dict) -> CheckResult:
    record_type = str(params.get("record_type", "A")).upper()
    try:
        records, latency = _resolve(host, params)
    except DnsLookupError as exc:
        return CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="dns_error")],
            msg=f"{record_type} lookup failed: {exc}",
        )

    samples = [Sample("avail", 1.0), Sample("latency_ms", latency)]
    details = {"records": records}
    expected = params.get("expected_values") or []
    if expected:
        matched = any(any(e in r for r in records) for e in expected)
        if not matched:
            samples[0] = Sample("avail", 0.0)
            return CheckResult(
                up=False,
                samples=samples,
                msg=f"{record_type} records {records} did not match expected {expected}",
                details=details,
            )
    return CheckResult(
        up=True,
        samples=samples,
        msg=f"{record_type}: {len(records)} record(s) in {latency}ms",
        details=details,
    )


register("dns", collect_dns)

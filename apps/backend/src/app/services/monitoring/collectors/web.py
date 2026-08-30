"""HTTP(S) check: status ranges, keyword, JSON path, TLS certificate capture."""

from __future__ import annotations

import json
import socket
import ssl
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.core.egress import PRIVATE_LAN_HTTP, httpx_request
from app.core.url_validation import (
    MONITOR_TARGET_POLICY,
    validate_outbound_url,
    validate_redirect_target,
)
from app.services.monitoring.collectors import CheckResult, Sample, register

if TYPE_CHECKING:
    import httpx

_DEFAULT_RANGES = ["200-299"]

#: httpx's own default redirect ceiling, applied to the manual hop loop.
_MAX_REDIRECTS = 20


def _request(url: str, params: dict) -> tuple[httpx.Response, float]:
    """One HTTP request. Returns (response, latency_ms). Mocked in tests."""

    # SEC-12: a monitor URL is attacker-influenced input — whoever can create a
    # monitor chooses the host, method, headers and body. Checking it here rather
    # than only at save time also covers rows created before this policy existed
    # and names that resolve somewhere new between save and check.
    validate_outbound_url(url, MONITOR_TARGET_POLICY)

    # B27 (dial-the-validated-address pinning) is deliberately NOT applied here,
    # and the finding stays open for this path. `pinned_request` must know
    # whether the request is going through a forward proxy — httpcore's CONNECT
    # tunnel ignores the `sni_hostname` extension the pin relies on, so pinning
    # a proxied HTTPS request fails certificate verification outright — and it
    # learns that from the client object. This collector sends through the
    # module-level `httpx.request`, which builds and discards its own Client, so
    # there is nothing to ask. What the pin would buy here is also the smallest
    # of any call site: MONITOR_TARGET_POLICY already permits loopback and
    # RFC1918, so the only rebinding it would block is a flip to link-local or
    # another reserved range. If this ever moves to an explicit `httpx.Client`,
    # pass it to `pinned_request` and keep the *name* form as the base for the
    # redirect `urljoin` below.

    method = str(params.get("method", "GET")).upper()
    headers = dict(params.get("headers") or {})
    auth_type = params.get("auth_type", "none")
    auth = None
    if auth_type == "basic":
        auth = (params.get("username", ""), params.get("password", ""))
    elif auth_type == "bearer" and params.get("token"):
        headers["Authorization"] = f"Bearer {params['token']}"
    t0 = time.monotonic()
    resp = httpx_request(
        method,
        url,
        policy=PRIVATE_LAN_HTTP,
        headers=headers or None,
        content=params.get("body") or None,
        timeout=float(params.get("timeout", 10.0)),
        # Redirects are followed manually below so each hop is re-validated: an
        # allowed target must not be able to bounce the check into link-local.
        follow_redirects=False,
        auth=auth,
        verify=bool(params.get("verify_tls", True)),
    )
    if bool(params.get("follow_redirects", True)):
        hops = 0
        while resp.is_redirect and hops < _MAX_REDIRECTS:
            target = validate_redirect_target(
                str(resp.request.url),
                resp.headers.get("location", ""),
                MONITOR_TARGET_POLICY,
            )
            resp = httpx_request(
                method,
                target.url,
                policy=PRIVATE_LAN_HTTP,
                headers=headers or None,
                content=params.get("body") or None,
                timeout=float(params.get("timeout", 10.0)),
                follow_redirects=False,
                auth=auth,
                verify=bool(params.get("verify_tls", True)),
            )
            hops += 1
    return resp, round((time.monotonic() - t0) * 1000, 2)


def _status_accepted(status: int, ranges: list[str]) -> bool:
    for r in ranges or _DEFAULT_RANGES:
        r = str(r).strip()
        if "-" in r:
            lo, _, hi = r.partition("-")
            try:
                if int(lo) <= status <= int(hi):
                    return True
            except ValueError:
                continue
        elif r.isdigit() and int(r) == status:
            return True
    return False


def _json_path(data: object, path: str) -> object:
    """Resolve a dotted path with optional [idx] segments; None if unresolvable."""
    cur = data
    for part in path.replace("]", "").split("."):
        for seg in part.split("["):
            if seg == "":
                continue
            if isinstance(cur, dict):
                cur = cur.get(seg)
            elif isinstance(cur, list) and seg.lstrip("-").isdigit():
                idx = int(seg)
                cur = cur[idx] if -len(cur) <= idx < len(cur) else None
            else:
                return None
    return cur


def _rdn_map(rdns: object) -> dict[str, str]:
    """Flatten an ssl RDN sequence — (((key, value),), ...) — into a plain dict."""
    out: dict[str, str] = {}
    if not isinstance(rdns, tuple):
        return out
    for rdn in rdns:
        if isinstance(rdn, tuple) and rdn and isinstance(rdn[0], tuple) and len(rdn[0]) == 2:
            out[str(rdn[0][0])] = str(rdn[0][1])
    return out


def _tls_details(url: str, timeout: float) -> dict | None:
    """Best-effort certificate capture for https URLs. Never raises."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    host = parsed.hostname
    port = parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        if not cert:
            return None
        not_after = cert.get("notAfter")
        if not isinstance(not_after, str):
            return None
        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        days = (expires - datetime.now(UTC)).days
        subject = _rdn_map(cert.get("subject", ()))
        issuer = _rdn_map(cert.get("issuer", ()))
        return {
            "tls": {
                "subject_cn": subject.get("commonName"),
                "issuer_cn": issuer.get("commonName"),
                "expires_at": expires.isoformat(),
                "days_remaining": days,
            }
        }
    except Exception:  # noqa: BLE001 — cert capture is auxiliary, never fails a check
        return None


def collect_http(host: str, params: dict) -> CheckResult:
    url = params.get("url") or f"http://{host}/"
    try:
        resp, latency = _request(url, params)
    except Exception as exc:  # noqa: BLE001 — network failure is a datum, not an error
        return CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="http_error")],
            msg=f"request failed: {type(exc).__name__}",
        )

    samples = [Sample("latency_ms", latency), Sample("http_status", float(resp.status_code))]
    details = _tls_details(url, float(params.get("timeout", 10.0)))
    if details and details["tls"].get("days_remaining") is not None:
        samples.append(Sample("cert_days_remaining", float(details["tls"]["days_remaining"])))

    if not _status_accepted(resp.status_code, params.get("accepted_statuses") or []):
        samples.insert(0, Sample("avail", 0.0))
        return CheckResult(
            up=False,
            samples=samples,
            msg=f"unexpected status {resp.status_code}",
            details=details,
        )

    keyword = params.get("keyword")
    if keyword:
        found = keyword in (resp.text or "")
        invert = bool(params.get("keyword_invert", False))
        if found == invert:
            samples.insert(0, Sample("avail", 0.0))
            verb = "found" if invert else "not found"
            return CheckResult(
                up=False,
                samples=samples,
                msg=f"keyword {verb}: {keyword!r}",
                details=details,
            )

    json_path = params.get("json_path")
    if json_path:
        try:
            value = _json_path(resp.json(), json_path)
        except (ValueError, json.JSONDecodeError):
            value = None
        expected = params.get("expected_value")
        if expected is not None and str(value) != str(expected):
            samples.insert(0, Sample("avail", 0.0))
            return CheckResult(
                up=False,
                samples=samples,
                msg=f"json {json_path} = {value!r}, expected {expected!r}",
                details=details,
            )

    samples.insert(0, Sample("avail", 1.0))
    return CheckResult(
        up=True,
        samples=samples,
        msg=f"{resp.status_code} in {latency}ms",
        details=details,
    )


register("http", collect_http)

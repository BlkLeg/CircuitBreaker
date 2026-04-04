"""OPNsense REST API client — fetches DHCP leases + ARP table and merges them.

OPNsense MVC routing converts PHP camelCaseAction() method names to snake_case
URL segments.  All endpoints use snake_case paths (e.g. get_arp, search_lease).
Authentication: HTTP Basic — API key as username, API secret as password.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _reject_ssrf_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if addr.is_loopback:
        raise ValueError("loopback address is not allowed")
    if addr.is_link_local:
        raise ValueError("link-local address is not allowed (includes cloud metadata endpoints)")


def _validate_opnsense_host(host: str) -> None:
    """Block loopback/link-local targets for literal IPs and for resolved DNS.

    Private LAN ranges remain allowed.  httpx requests use follow_redirects=False
    so a 302 to an internal URL cannot bypass this check.
    """
    host = host.strip()
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(
                host,
                443,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            raise ValueError(f"OPNsense: cannot resolve host {host!r} — {exc}") from exc
        if not infos:
            raise ValueError(f"OPNsense: host {host!r} did not resolve to any address")
        seen: set[str] = set()
        for info in infos:
            ip_str = info[4][0]
            if ip_str in seen:
                continue
            seen.add(ip_str)
            try:
                resolved = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            try:
                _reject_ssrf_ip(resolved)
            except ValueError as exc:
                raise ValueError(
                    f"OPNsense: host {host!r} resolves to {ip_str}, which is not allowed ({exc})"
                ) from exc
        return

    try:
        _reject_ssrf_ip(addr)
    except ValueError as exc:
        raise ValueError(f"OPNsense: host {host!r} is a {exc}") from exc


# ── Endpoint constants ────────────────────────────────────────────────────────

_ARP_PATH = "/api/diagnostics/interface/get_arp"
_KEA_LEASES_PATH = "/api/kea/leases4/search"
_ISC_LEASES_PATH = "/api/dhcpv4/leases/search_lease"
_SYSINFO_PATH = "/api/diagnostics/system/system_information"
_MEMORY_PATH = "/api/diagnostics/system/memory"
_PING_PATH = "/api/diagnostics/ping/execute"


def _build_client_kwargs(settings: dict[str, Any]) -> tuple[str, str, str, bool]:
    """Parse and validate settings. Returns (base_url, api_key, api_secret, verify_ssl).

    Raises ValueError with a descriptive message on missing/invalid config.
    Decrypts Fernet-encrypted credentials via credential_vault.
    """
    raw_host = (settings.get("opnsense_host") or "").strip()
    for scheme in ("https://", "http://"):
        if raw_host.lower().startswith(scheme):
            raw_host = raw_host[len(scheme) :]
            break
    host = raw_host.rstrip("/")

    if not host:
        raise ValueError("OPNsense: host not configured")

    _validate_opnsense_host(host)

    key_enc = settings.get("opnsense_api_key_enc") or ""
    secret_enc = settings.get("opnsense_api_secret_enc") or ""
    if not key_enc or not secret_enc:
        raise ValueError("OPNsense: API credentials not configured")

    from app.services.credential_vault import get_vault

    vault = get_vault()
    api_key = vault.decrypt(key_enc)
    api_secret = vault.decrypt(secret_enc)

    verify_ssl = bool(settings.get("opnsense_verify_ssl", False))
    return f"https://{host}", api_key, api_secret, verify_ssl


async def fetch_opnsense_devices(
    settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch devices from OPNsense DHCP leases and ARP table.

    Returns (devices, error_message). error_message is None on success.
    ARP is required — any 4xx on the ARP endpoint returns ([], error).

    Each device dict: {mac, ip, hostname, source, is_active, expires}
    """
    try:
        base_url, api_key, api_secret, verify_ssl = _build_client_kwargs(settings)
    except ValueError as exc:
        return [], str(exc)
    except Exception as exc:
        return [], f"OPNsense: failed to decrypt credentials — {exc}"

    try:
        async with httpx.AsyncClient(
            auth=(api_key, api_secret),
            verify=verify_ssl,
            timeout=10.0,
            follow_redirects=False,
        ) as client:
            # ── DHCP leases ────────────────────────────────────────────────
            # Try Kea (24.1+) first, then ISC DHCP (< 24.1).
            # Leases are enrichment — ARP is ground truth.
            leases_data: list | dict = []
            kea_used = False

            for lease_path in (_KEA_LEASES_PATH, _ISC_LEASES_PATH):
                resp = await client.get(f"{base_url}{lease_path}")
                if resp.status_code == 404:
                    logger.debug("OPNsense: GET %s → 404, trying fallback", lease_path)
                    continue
                if resp.status_code == 401:
                    return [], "OPNsense: unauthorized — check API key and secret"
                if resp.status_code == 403:
                    try:
                        detail = resp.json().get("message") or resp.text[:200]
                    except Exception:
                        detail = resp.text[:200]
                    logger.warning("OPNsense: lease endpoint 403 (%s) — %s", lease_path, detail)
                    break
                resp.raise_for_status()
                leases_data = resp.json()
                kea_used = lease_path == _KEA_LEASES_PATH
                logger.debug("OPNsense: leases fetched via GET %s (kea=%s)", lease_path, kea_used)
                break
            else:
                logger.warning("OPNsense: DHCP leases unavailable — proceeding ARP-only")

            # ── ARP table (required) ──────────────────────────────────────
            arp_resp = await client.get(f"{base_url}{_ARP_PATH}")
            if arp_resp.status_code == 401:
                return [], "OPNsense: unauthorized — check API key and secret"
            if arp_resp.status_code == 403:
                return [], (
                    "OPNsense: ARP endpoint forbidden (403) — "
                    "add 'Diagnostics: ARP Table' privilege to the API user"
                )
            if arp_resp.status_code == 404:
                return [], (
                    f"OPNsense: ARP endpoint not found (404) at {_ARP_PATH} — "
                    "verify OPNsense version and API URL"
                )
            arp_resp.raise_for_status()
            arp_data = arp_resp.json()

    except httpx.ConnectError as exc:
        host = (settings.get("opnsense_host") or "").strip()
        return [], f"OPNsense: connection refused ({host}) — {exc}"
    except httpx.TimeoutException:
        host = (settings.get("opnsense_host") or "").strip()
        return [], f"OPNsense: request timed out ({host})"
    except httpx.HTTPStatusError as exc:
        return [], f"OPNsense: HTTP {exc.response.status_code} from {exc.request.url}"
    except Exception as exc:
        return [], f"OPNsense: unexpected error — {exc}"

    return _merge_devices(leases_data, arp_data), None


async def fetch_opnsense_stats(
    settings: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Fetch system_information + memory from OPNsense.

    Returns (stats_dict, error_message).
    stats_dict keys: version, uptime, cpu_load, mem_total, mem_used, mem_percent
    """
    try:
        base_url, api_key, api_secret, verify_ssl = _build_client_kwargs(settings)
    except (ValueError, Exception) as exc:
        return {}, str(exc)

    try:
        async with httpx.AsyncClient(
            auth=(api_key, api_secret),
            verify=verify_ssl,
            timeout=10.0,
            follow_redirects=False,
        ) as client:
            sysinfo_resp = await client.get(f"{base_url}{_SYSINFO_PATH}")
            if sysinfo_resp.status_code == 401:
                return {}, "OPNsense: unauthorized — check API key and secret"
            sysinfo_resp.raise_for_status()
            sysinfo = sysinfo_resp.json()

            mem_resp = await client.get(f"{base_url}{_MEMORY_PATH}")
            mem_resp.raise_for_status()
            mem = mem_resp.json()

    except httpx.ConnectError as exc:
        host = (settings.get("opnsense_host") or "").strip()
        return {}, f"OPNsense: connection refused ({host}) — {exc}"
    except httpx.TimeoutException:
        host = (settings.get("opnsense_host") or "").strip()
        return {}, f"OPNsense: request timed out ({host})"
    except httpx.HTTPStatusError as exc:
        return {}, f"OPNsense: HTTP {exc.response.status_code} from {exc.request.url}"
    except Exception as exc:
        return {}, f"OPNsense: unexpected error — {exc}"

    # Normalise the response into a flat stats dict
    stats: dict[str, Any] = {}

    # system_information fields
    if isinstance(sysinfo, dict):
        stats["version"] = sysinfo.get("product_version") or sysinfo.get("version")
        stats["uptime"] = sysinfo.get("uptime")
        load = sysinfo.get("cpu_load") or sysinfo.get("loadavg") or sysinfo.get("load")
        if isinstance(load, list) and len(load) >= 3:
            stats["cpu_load_1"] = load[0]
            stats["cpu_load_5"] = load[1]
            stats["cpu_load_15"] = load[2]
        elif isinstance(load, str):
            parts = load.split(",")
            if len(parts) >= 3:
                stats["cpu_load_1"] = parts[0].strip()
                stats["cpu_load_5"] = parts[1].strip()
                stats["cpu_load_15"] = parts[2].strip()

    # memory fields
    if isinstance(mem, dict):
        total = mem.get("total") or mem.get("physmem")
        used = mem.get("used") or mem.get("wired")
        if total and used:
            try:
                stats["mem_total"] = int(total)
                stats["mem_used"] = int(used)
                stats["mem_percent"] = round(int(used) / int(total) * 100, 1)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

    return stats, None


async def ping_via_opnsense(
    settings: dict[str, Any],
    target_ip: str,
) -> tuple[dict[str, Any], str | None]:
    """Ping target_ip via OPNsense diagnostics ping endpoint.

    POST /api/diagnostics/ping/execute
    Returns (ping_result, error_message).
    ping_result keys: min_rtt, avg_rtt, max_rtt, packet_loss, raw
    """
    try:
        base_url, api_key, api_secret, verify_ssl = _build_client_kwargs(settings)
    except (ValueError, Exception) as exc:
        return {}, str(exc)

    try:
        async with httpx.AsyncClient(
            auth=(api_key, api_secret),
            verify=verify_ssl,
            timeout=15.0,
            follow_redirects=False,
        ) as client:
            resp = await client.post(
                f"{base_url}{_PING_PATH}",
                json={"host": target_ip, "count": 4},
            )
            if resp.status_code == 401:
                return {}, "OPNsense: unauthorized — check API key and secret"
            resp.raise_for_status()
            data = resp.json()

    except httpx.ConnectError as exc:
        host = (settings.get("opnsense_host") or "").strip()
        return {}, f"OPNsense: connection refused ({host}) — {exc}"
    except httpx.TimeoutException:
        host = (settings.get("opnsense_host") or "").strip()
        return {}, f"OPNsense: ping timed out ({host})"
    except httpx.HTTPStatusError as exc:
        return {}, f"OPNsense: HTTP {exc.response.status_code} from {exc.request.url}"
    except Exception as exc:
        return {}, f"OPNsense: unexpected error — {exc}"

    # Normalise ping response
    result: dict[str, Any] = {"raw": data}
    if isinstance(data, dict):
        result["min_rtt"] = data.get("min_rtt") or data.get("min")
        result["avg_rtt"] = data.get("avg_rtt") or data.get("avg")
        result["max_rtt"] = data.get("max_rtt") or data.get("max")
        result["packet_loss"] = data.get("packet_loss") or data.get("loss")

    return result, None


# ── Test-connection helper ────────────────────────────────────────────────────


async def test_opnsense_connection(
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Run a structured connectivity test against OPNsense.

    Returns {ok, version, arp_count, lease_count, kea, error}.
    """
    try:
        base_url, api_key, api_secret, verify_ssl = _build_client_kwargs(settings)
    except (ValueError, Exception) as exc:
        return {"ok": False, "error": str(exc)}

    try:
        async with httpx.AsyncClient(
            auth=(api_key, api_secret),
            verify=verify_ssl,
            timeout=10.0,
            follow_redirects=False,
        ) as client:
            # System info for version
            version: str | None = None
            try:
                si_resp = await client.get(f"{base_url}{_SYSINFO_PATH}")
                if si_resp.status_code == 200:
                    si = si_resp.json()
                    if isinstance(si, dict):
                        version = si.get("product_version") or si.get("version")
            except Exception:
                pass

            # ARP — required
            arp_resp = await client.get(f"{base_url}{_ARP_PATH}")
            if arp_resp.status_code == 401:
                return {"ok": False, "error": "OPNsense: unauthorized — check API key and secret"}
            if arp_resp.status_code == 403:
                return {
                    "ok": False,
                    "error": (
                        "OPNsense: ARP endpoint forbidden (403) — "
                        "add 'Diagnostics: ARP Table' privilege to the API user"
                    ),
                }
            if arp_resp.status_code == 404:
                return {
                    "ok": False,
                    "error": f"OPNsense: ARP endpoint not found (404) at {_ARP_PATH}",
                }
            arp_resp.raise_for_status()
            arp_data = arp_resp.json()
            arp_rows = arp_data if isinstance(arp_data, list) else arp_data.get("rows", [])
            arp_count = len(arp_rows)

            # Leases (enrichment — failure is non-fatal for test)
            lease_count = 0
            kea = False
            for lease_path in (_KEA_LEASES_PATH, _ISC_LEASES_PATH):
                l_resp = await client.get(f"{base_url}{lease_path}")
                if l_resp.status_code == 404:
                    continue
                if l_resp.status_code in (401, 403):
                    break
                if l_resp.status_code == 200:
                    ld = l_resp.json()
                    rows = ld if isinstance(ld, list) else ld.get("rows", [])
                    lease_count = len(rows)
                    kea = lease_path == _KEA_LEASES_PATH
                    break

    except httpx.ConnectError as exc:
        host = (settings.get("opnsense_host") or "").strip()
        return {"ok": False, "error": f"OPNsense: connection refused ({host}) — {exc}"}
    except httpx.TimeoutException:
        host = (settings.get("opnsense_host") or "").strip()
        return {"ok": False, "error": f"OPNsense: request timed out ({host})"}
    except httpx.HTTPStatusError as exc:
        return {
            "ok": False,
            "error": f"OPNsense: HTTP {exc.response.status_code} from {exc.request.url}",
        }
    except Exception as exc:
        return {"ok": False, "error": f"OPNsense: unexpected error — {exc}"}

    return {
        "ok": True,
        "version": version,
        "arp_count": arp_count,
        "lease_count": lease_count,
        "kea": kea,
        "error": None,
    }


# ── Merge logic ───────────────────────────────────────────────────────────────


def _merge_devices(
    leases_data: Any,
    arp_data: Any,
) -> list[dict[str, Any]]:
    """Merge OPNsense lease and ARP data into a unified device list.

    Merge rules:
    - ARP entries → is_active=True, source='opnsense_arp'
    - Lease entries add hostname, expiry; source becomes 'opnsense_lease'
    - ARP-only (no lease) → is_active=True, hostname=None
    - Lease-only (not in ARP) → is_active=False
    """
    arp_rows = arp_data if isinstance(arp_data, list) else arp_data.get("rows", [])
    arp_by_ip: dict[str, str] = {}
    for entry in arp_rows:
        ip = (entry.get("ip") or "").strip()
        mac = (entry.get("mac") or "").strip().lower()
        if ip and mac:
            arp_by_ip[ip] = mac

    devices: dict[str, dict[str, Any]] = {}
    for ip, mac in arp_by_ip.items():
        devices[ip] = {
            "ip": ip,
            "mac": mac,
            "hostname": None,
            "source": "opnsense_arp",
            "is_active": True,
            "expires": None,
        }

    lease_rows = leases_data if isinstance(leases_data, list) else leases_data.get("rows", [])
    for entry in lease_rows:
        ip = (entry.get("address") or "").strip()
        mac = (entry.get("mac") or "").strip().lower()
        hostname = (entry.get("hostname") or "").strip() or None
        expires = entry.get("ends") or None

        if not ip:
            continue

        is_active = ip in arp_by_ip

        if ip in devices:
            devices[ip].update(
                {
                    "mac": mac or devices[ip]["mac"],
                    "hostname": hostname,
                    "source": "opnsense_lease",
                    "expires": expires,
                }
            )
        else:
            devices[ip] = {
                "ip": ip,
                "mac": mac,
                "hostname": hostname,
                "source": "opnsense_lease",
                "is_active": is_active,
                "expires": expires,
            }

    return list(devices.values())

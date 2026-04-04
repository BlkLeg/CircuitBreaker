"""Comprehensive device fingerprinting — all probes are L0 (fully unprivileged).

Provides:
  - _run_rdns_probe          — DNS PTR lookup
  - _run_netbios_probe       — UDP NetBIOS Node Status (RFC 1002)
  - _run_ssdp_unicast_probe  — UPnP description XML fetch (Fire TV, printers, routers …)
  - _run_mdns_probe          — Unicast mDNS service queries (iPhone, Android, Chromecast …)
  - _parse_banner_for_hints  — Regex banner parser (OS / vendor / device type)
  - _run_http_fingerprint_probe — HTTP HEAD + page-title scrape
  - _run_vendor_lookup_local — Offline OUI database (manuf), falls back to API
  - _classify_device         — evidence → (device_type, confidence 0–100)
  - _coalesce_host_info      — priority-ordered merge of all probe results
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
import socket
import struct
from pathlib import Path
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

# ── Timeouts ──────────────────────────────────────────────────────────────────
_RDNS_TIMEOUT: float = 2.0
_NETBIOS_TIMEOUT: float = 2.0
_SSDP_TIMEOUT: float = 3.0
_MDNS_TIMEOUT: float = 4.0
_HTTP_TIMEOUT: float = 3.0
_MDNS_MULTICAST_GROUP = "224.0.0.251"
_MDNS_PORT = 5353

# ── Optional dependency guards ────────────────────────────────────────────────
try:
    import zeroconf as _zeroconf_check  # noqa: F401 — availability check only

    del _zeroconf_check

    _ZEROCONF_AVAILABLE = True
except ImportError:
    _ZEROCONF_AVAILABLE = False

try:
    import manuf as _manuf_module  # type: ignore[import-untyped]

    _MANUF_PARSER = _manuf_module.MacParser()
    _MANUF_AVAILABLE = True
except Exception:
    _MANUF_PARSER = None
    _MANUF_AVAILABLE = False


# ───────────────────────────────────────────────────────────────────────────────
# Mobile device helpers
# ───────────────────────────────────────────────────────────────────────────────


def _is_randomized_mac(mac: str) -> bool:
    """Return True if *mac* has the locally-administered (randomized) bit set.

    According to IEEE 802, the U/L (Universal/Local) bit is bit 1 of the first octet.
    When set to 1 the address was generated locally (privacy / randomized MAC).
    Example OUIs with this bit set: 02:xx, 06:xx, 0a:xx, 0e:xx, ...
    """
    if not mac:
        return False
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0x02)
    except (ValueError, IndexError):
        return False


async def _probe_ip_ttl(ip: str) -> int | None:
    """Ping *ip* once and return the TTL from the ICMP response.

    TTL interpretation:
      55–65  → Linux / Android / iOS (kernel default 64 with some hops)
      120–130 → Windows (default TTL 128)
      250–260 → Network device (router/switch, default 255)

    Parses TTL from subprocess ``ping -c1 -W1`` output.
    Returns None on failure (host unreachable, no response, etc.).
    """
    # Parse TTL from ping output
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c1",
            "-W1",
            ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        output = stdout.decode(errors="replace")
        # Matches: "ttl=64" or "TTL=128"
        ttl_m = re.search(r"\bttl=(\d+)\b", output, re.IGNORECASE)
        if ttl_m:
            return int(ttl_m.group(1))
    except Exception:
        pass
    return None


# mDNS service types that indicate a phone or mobile device
_MOBILE_MDNS_SERVICES = frozenset(
    {
        "_apple-mobdev2._tcp",
        "_apple-mobdev._tcp",
        "_companion-link._tcp",  # iPhone/iPad Handoff / Continuity
        "_rdlink._tcp",  # iPhone Universal Clipboard
        "_androidtvremote2._tcp",
        "_googlecast._tcp",  # Chromecast / Android phones with cast
        "_sleep-proxy._udp",  # iOS network wake proxy
        "_remotepairing._tcp",  # iPhone/Mac Remote Pairing
    }
)


async def _run_mdns_multicast_listener(duration_s: float = 8.0) -> list[dict]:
    """Passive mDNS multicast listener.

    Joins the mDNS multicast group 224.0.0.251 on UDP port 5353 and
    collects ALL mDNS announcements for *duration_s* seconds.  Any
    announcement reveals both the source IP and (via PTR records) the
    service type the device is advertising.

    This complements _run_mdns_probe (which sends unicast queries to
    *named* service instances) by discovering devices before we know
    their instance names — exactly what is needed for phones.

    No root privileges required: multicast group joins are unprivileged
    on Linux/macOS as long as we bind to a non-reserved port or use
    SO_REUSEPORT.  We bind to 5353 with SO_REUSEADDR so multiple
    processes can co-exist.

    Returns [{"ip", "hostname", "services": [str], "device_type_hint",
               "os_hint", "is_mobile_mdns": bool}]
    """
    import socket as _socket
    import struct as _struct
    import threading

    discovered: dict[str, dict] = {}  # ip → accumulated info
    lock = threading.Lock()

    def _parse_dns_name(data: bytes, offset: int) -> tuple[str, int]:
        """Parse a DNS name from wire format, handling compression pointers."""
        labels: list[str] = []
        visited: set[int] = set()
        while offset < len(data):
            if offset in visited:
                break
            visited.add(offset)
            length = data[offset]
            if length == 0:
                offset += 1
                break
            if (length & 0xC0) == 0xC0:  # Compression pointer
                if offset + 1 >= len(data):
                    break
                ptr = ((length & 0x3F) << 8) | data[offset + 1]
                name_suffix, _ = _parse_dns_name(data, ptr)
                if name_suffix:
                    labels.append(name_suffix)
                offset += 2
                break
            try:
                labels.append(
                    data[offset + 1 : offset + 1 + length].decode("utf-8", errors="replace")
                )
            except Exception:
                pass
            offset += 1 + length
        return ".".join(labels), offset

    def _parse_mdns_packet(data: bytes, src_ip: str) -> None:
        """Extract service / hostname info from a raw mDNS DNS packet."""
        if len(data) < 12:
            return
        try:
            an_count = _struct.unpack_from("!H", data, 6)[0]
            ar_count = _struct.unpack_from("!H", data, 10)[0]
        except Exception:
            return

        offset = 12
        # Skip question section (qdcount answers in query, we mostly see responses)
        qdcount = _struct.unpack_from("!H", data, 4)[0]
        for _ in range(qdcount):
            try:
                _, offset = _parse_dns_name(data, offset)
                offset += 4  # QTYPE + QCLASS
            except Exception:
                return

        services_found: list[str] = []
        hostname_found: str | None = None

        for _ in range(an_count + ar_count):
            if offset >= len(data):
                break
            try:
                name, offset = _parse_dns_name(data, offset)
                if offset + 10 > len(data):
                    break
                rtype, _, _, rdlen = _struct.unpack_from("!HHIH", data, offset)
                offset += 10
                _rdata = data[offset : offset + rdlen]  # noqa: F841
                offset += rdlen

                if rtype == 12:  # PTR — service advertisement
                    # name is like "_apple-mobdev2._tcp.local." — extract type
                    if "._tcp." in name or "._udp." in name:
                        svc_type = name.split(".")[0] + ("._tcp" if "._tcp." in name else "._udp")
                        services_found.append(svc_type)
                elif rtype == 1 and rdlen == 4:  # A record — IP
                    pass  # src_ip from socket is more reliable
                elif rtype == 33:  # SRV
                    pass
                elif rtype == 28:  # AAAA — IPv6, skip
                    pass
            except Exception:
                break

        with lock:
            entry = discovered.setdefault(
                src_ip,
                {
                    "ip": src_ip,
                    "hostname": hostname_found,
                    "services": [],
                    "device_type_hint": None,
                    "os_hint": None,
                    "is_mobile_mdns": False,
                },
            )
            for svc in services_found:
                if svc not in entry["services"]:
                    entry["services"].append(svc)
            if hostname_found and not entry["hostname"]:
                entry["hostname"] = hostname_found
            if any(s in _MOBILE_MDNS_SERVICES for s in services_found):
                entry["is_mobile_mdns"] = True
                entry["device_type_hint"] = "mobile_device"
            # Apple services broadly → ios_device if no better hint yet
            if any("apple" in s for s in services_found) and not entry.get("device_type_hint"):
                entry["device_type_hint"] = "ios_device"
                entry["os_hint"] = "iOS"

    # Set up the multicast socket
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass  # Not available on all platforms
        sock.bind(("", _MDNS_PORT))  # nosec B104 — mDNS multicast requires binding to all interfaces
        mreq = _struct.pack("4sL", _socket.inet_aton(_MDNS_MULTICAST_GROUP), _socket.INADDR_ANY)
        sock.setsockopt(_socket.IPPROTO_IP, _socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(0.1)  # Non-blocking reads
    except Exception as exc:
        logger.warning("mDNS multicast listener: socket setup failed: %s", exc)
        return []

    loop = asyncio.get_running_loop()
    end_time = loop.time() + duration_s

    try:
        while loop.time() < end_time:
            remaining = end_time - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: _recv_and_parse(sock, _parse_mdns_packet),
                    ),
                    timeout=min(remaining, 0.5),
                )
            except (TimeoutError, Exception):
                pass
    finally:
        try:
            sock.close()
        except Exception:
            pass

    results = list(discovered.values())
    mobile_count = sum(1 for r in results if r.get("is_mobile_mdns"))
    logger.info(
        "mDNS multicast listener: %.1fs, %d unique IPs (%d mobile)",
        duration_s,
        len(results),
        mobile_count,
    )
    return results


def _recv_and_parse(
    sock: socket.socket,  # type: ignore[name-defined]
    callback: Any,
) -> None:
    """Blocking recv loop called from run_in_executor for 0.5s."""
    import time

    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
            callback(data, addr[0])
        except Exception:
            break


async def _run_mdns_browse(timeout: float = 8.0) -> list[dict]:  # noqa: ASYNC109
    """Active DNS-SD browse — enumerate ALL service types on the network.

    Queries ``_services._dns-sd._udp.local.`` PTR, which returns the list
    of all service types currently registered on the link-local network.
    For each service type, resolves instances via PTR→SRV→A to obtain
    the IP address.

    This discovers devices that haven't responded to any unicast queries
    because we didn't know their instance names beforehand.

    Requires ``zeroconf`` (already in requirements.txt).

    Returns [{"ip", "hostname", "services": [str], "device_type_hint"}]
    """
    if not _ZEROCONF_AVAILABLE:
        logger.debug("_run_mdns_browse: zeroconf not available")
        return []

    import ipaddress as _ipaddress

    from zeroconf import ServiceBrowser, ServiceListener  # type: ignore[import]
    from zeroconf.asyncio import AsyncZeroconf  # type: ignore[import]

    discovered: dict[str, dict] = {}  # ip → info
    # Records (service_type, instance_name) pairs from the browser callbacks.
    # add_service(zc, type_, name) — name IS the fully-qualified instance name,
    # e.g. "John's iPhone._apple-mobdev2._tcp.local."  We need the instance name
    # to construct ServiceInfo correctly.
    found_instances: list[tuple[str, str]] = []

    _COMMON_MOBILE_SERVICES = [
        "_apple-mobdev2._tcp.local.",
        "_apple-mobdev._tcp.local.",
        "_companion-link._tcp.local.",
        "_rdlink._tcp.local.",
        "_androidtvremote2._tcp.local.",
        "_googlecast._tcp.local.",
        "_sleep-proxy._udp.local.",
        "_remotepairing._tcp.local.",
        # Broad services that phones advertise
        "_http._tcp.local.",
        "_ipp._tcp.local.",
        "_airplay._tcp.local.",
        "_raop._tcp.local.",
    ]

    try:
        aiozc = AsyncZeroconf()
        await aiozc.zeroconf.async_wait_for_start()

        class _InstanceListener(ServiceListener):
            def add_service(self, zc: Any, type_: str, name: str) -> None:  # noqa: A002
                # name is the fully-qualified instance name (not the type)
                found_instances.append((type_, name))

            def remove_service(self, zc: Any, type_: str, name: str) -> None:  # noqa: A002
                pass

            def update_service(self, zc: Any, type_: str, name: str) -> None:  # noqa: A002
                pass

        listener = _InstanceListener()
        for svc in _COMMON_MOBILE_SERVICES:
            ServiceBrowser(aiozc.zeroconf, svc, listener=listener)

        # Half the budget for passive listening, half for concurrent resolution
        await asyncio.sleep(min(timeout * 0.4, 3.0))

        from zeroconf import ServiceInfo  # type: ignore[import]

        async def _resolve_instance(type_: str, name: str) -> None:
            """Resolve one service instance to an IP and merge into discovered."""
            try:
                info = ServiceInfo(type_, name)
                # request() is synchronous — run in thread to stay non-blocking
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    functools.partial(info.request, aiozc.zeroconf, 1500),
                )
                if not info.addresses:
                    return
                for raw_addr in info.addresses:
                    try:
                        ip = str(_ipaddress.IPv4Address(raw_addr))
                    except Exception:
                        continue
                    svc_key = type_.rstrip(".").replace(".local", "")
                    entry = discovered.setdefault(
                        ip,
                        {
                            "ip": ip,
                            "hostname": info.server.rstrip(".") if info.server else None,
                            "services": [],
                            "device_type_hint": None,
                        },
                    )
                    if svc_key not in entry["services"]:
                        entry["services"].append(svc_key)
                    clean = svc_key.split(".")[0]
                    if clean in _MOBILE_MDNS_SERVICES:
                        entry["device_type_hint"] = "mobile_device"
            except Exception:
                pass

        # Resolve all found instances concurrently — avoids 2s-per-instance
        # sequential timeouts that previously blew the 10s outer budget.
        if found_instances:
            await asyncio.gather(*[_resolve_instance(t, n) for t, n in set(found_instances)])

    except Exception as exc:
        logger.debug("_run_mdns_browse: error: %s", exc)
    finally:
        try:
            await aiozc.async_close()
        except Exception:
            pass

    logger.info("_run_mdns_browse: found %d unique IPs", len(discovered))
    return list(discovered.values())


# ─────────────────────────────────────────────────────────────────────────────
# KB loader + lookup helpers
# ─────────────────────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _load_device_kb() -> dict:
    """Load device_kb.json once. Returns empty dicts on failure."""
    kb_path = Path(__file__).parent.parent / "data" / "device_kb.json"
    try:
        with open(kb_path) as f:
            return cast(dict, json.load(f))
    except Exception:
        logger.warning("Discovery: device_kb.json missing or invalid — KB lookups disabled")
        return {"mac_oui_prefixes": {}, "hostname_patterns": []}


def _kb_oui_lookup(mac: str) -> dict | None:
    """Check curated KB for 6-char OUI prefix. Returns entry dict or None."""
    if not mac:
        return None
    normalized = mac.upper().replace(":", "").replace("-", "")[:6]
    return cast(dict | None, _load_device_kb()["mac_oui_prefixes"].get(normalized))


def _kb_hostname_hints(hostname: str, scan_hostname_cache: list[dict] | None = None) -> dict:
    """Return vendor/os_family/device_type hints from hostname pattern rules.

    When scan_hostname_cache is provided (pre-built per-scan merged list), it is used
    directly — avoiding repeated JSON loads and DB queries per device.
    Falls back to device_kb.json when no cache is injected (e.g. standalone callers).
    Handles both 'match' (JSON legacy key) and 'match_type' (DB column name).
    """
    if not hostname:
        return {}
    rules = (
        scan_hostname_cache
        if scan_hostname_cache is not None
        else _load_device_kb().get("hostname_patterns", [])
    )
    hn = hostname.lower().strip()
    for rule in rules:
        pat = rule["pattern"].lower()
        m = rule.get("match_type") or rule.get("match", "prefix")
        if (
            (m == "prefix" and hn.startswith(pat))
            or (m == "exact" and hn == pat)
            or (m == "contains" and pat in hn)
        ):
            return {
                k: v
                for k, v in rule.items()
                if k not in ("pattern", "match", "match_type") and v is not None
            }
    return {}


def _parse_snmp_sysdescr(sysdescr: str) -> dict:
    """Extract vendor/os_family hints from SNMP sysDescr string."""
    if not sysdescr:
        return {}
    desc = sysdescr.lower()
    for keyword, result in [
        ("proxmox", {"vendor": "Proxmox Server Solutions GmbH", "os_family": "Linux"}),
        ("opnsense", {"vendor": "OPNsense", "os_family": "FreeBSD"}),
        ("pfsense", {"vendor": "pfSense", "os_family": "FreeBSD"}),
        ("truenas", {"vendor": "TrueNAS", "os_family": "Linux"}),
        ("synology", {"vendor": "Synology", "os_family": "Linux"}),
        ("ubuntu", {"vendor": "Ubuntu", "os_family": "Linux"}),
        ("debian", {"vendor": "Debian", "os_family": "Linux"}),
        ("centos", {"vendor": "CentOS", "os_family": "Linux"}),
        ("windows", {"os_family": "Windows"}),
        ("freebsd", {"os_family": "FreeBSD"}),
        ("linux", {"os_family": "Linux"}),
    ]:
        if keyword in desc:
            return result
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 1. rDNS PTR lookup
# ─────────────────────────────────────────────────────────────────────────────


async def _run_rdns_probe(ip: str) -> str | None:
    """Resolve IP → hostname via DNS PTR record.  No root needed; 2 s timeout."""
    loop = asyncio.get_running_loop()
    try:
        hostname, *_ = await asyncio.wait_for(
            loop.run_in_executor(None, socket.gethostbyaddr, ip),
            timeout=_RDNS_TIMEOUT,
        )
        fqdn = hostname.rstrip(".")
        return fqdn if fqdn and fqdn != ip else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. NetBIOS Node Status Request (UDP 137, RFC 1002)
# ─────────────────────────────────────────────────────────────────────────────

_NETBIOS_NS_PORT = 137

# Fixed 50-byte NBSTAT request per RFC 1002 §4.2.18
_NBSTAT_REQUEST = (
    b"\xab\xcd"  # transaction ID (arbitrary)
    b"\x00\x00"  # flags: request, not recursive
    b"\x00\x01"  # QDCOUNT = 1
    b"\x00\x00"  # ANCOUNT
    b"\x00\x00"  # NSCOUNT
    b"\x00\x00"  # ARCOUNT
    # Question: encoded "*" wildcard (single asterisk encodes to 32 bytes of CA/CB)
    b"\x20"  # length prefix: 32
    b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # encoded "*"
    b"\x00"  # root label
    b"\x00\x21"  # QTYPE: NBSTAT (0x0021)
    b"\x00\x01"  # QCLASS: IN
)


def _decode_netbios_name(raw: bytes) -> str:
    """Strip trailing spaces and null bytes from a 15-byte NetBIOS name."""
    return raw.rstrip(b" \x00").decode("ascii", errors="replace")


async def _run_netbios_probe(ip: str) -> dict[str, str | None]:
    """Send a NetBIOS Node Status request and parse the response.

    Returns ``{hostname, workgroup, nb_type}`` or empty dict on failure.
    Completely unprivileged — uses standard UDP sendto/recvfrom.
    """
    loop = asyncio.get_running_loop()

    def _probe() -> dict[str, str | None]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(_NETBIOS_TIMEOUT)
                sock.sendto(_NBSTAT_REQUEST, (ip, _NETBIOS_NS_PORT))
                data, _ = sock.recvfrom(1024)
        except Exception:
            return {}

        # Parse response: skip 56-byte header, then name count byte
        try:
            if len(data) < 57:
                return {}
            name_count = data[56]
            offset = 57
            hostname: str | None = None
            workgroup: str | None = None
            for _ in range(name_count):
                if offset + 18 > len(data):
                    break
                raw_name = data[offset : offset + 15]
                nb_type = data[offset + 15]
                flags = struct.unpack_from(">H", data, offset + 16)[0]
                name_str = _decode_netbios_name(raw_name)
                # Type 0x00 with group=False → workstation name
                # Type 0x00 with group=True  → workgroup/domain
                # Type 0x20                  → file server
                is_group = bool(flags & 0x8000)
                if nb_type in (0x00, 0x20) and not is_group and not hostname:
                    hostname = name_str
                if nb_type == 0x00 and is_group and not workgroup:
                    workgroup = name_str
                offset += 18
            return {"hostname": hostname, "workgroup": workgroup}
        except Exception:
            return {}

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _probe),
            timeout=_NETBIOS_TIMEOUT + 0.5,
        )
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. SSDP / UPnP unicast probe
# ─────────────────────────────────────────────────────────────────────────────

_UPNP_DESCRIPTION_PORTS = (1900, 49152, 49153, 5000, 8200, 8080, 80, 8060)


async def _run_ssdp_unicast_probe(ip: str, open_ports: list[dict]) -> dict[str, str | None]:
    """Fetch the UPnP device description XML from a host's open ports.

    Tries common UPnP description URL paths against open HTTP ports.
    Returns ``{vendor, model, device_type_hint, friendly_name}`` or empty dict.
    No root; uses httpx which is already a project dependency.
    """
    open_port_nums = {int(p.get("port", 0)) for p in open_ports if p.get("port")}
    targets = [p for p in _UPNP_DESCRIPTION_PORTS if p in open_port_nums]
    if not targets:
        # Try the SSDP default even without it appearing in nmap results
        targets = [49152, 80]

    upnp_paths = ["/rootDesc.xml", "/description.xml", "/upnp/rootdevice.xml", "/setup.xml"]

    xml_re_map = {
        "friendly_name": re.compile(r"<friendlyName>(.*?)</friendlyName>", re.I | re.S),
        "manufacturer": re.compile(r"<manufacturer>(.*?)</manufacturer>", re.I | re.S),
        "model": re.compile(r"<modelName>(.*?)</modelName>", re.I | re.S),
        "device_type": re.compile(r"<deviceType>(.*?)</deviceType>", re.I | re.S),
    }

    async with httpx.AsyncClient(
        timeout=_SSDP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for port in targets:
            scheme = "https" if port == 443 else "http"
            for path in upnp_paths:
                url = f"{scheme}://{ip}:{port}{path}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    ct = resp.headers.get("content-type", "")
                    if "xml" not in ct and "text" not in ct:
                        continue
                    body = resp.text
                    result: dict[str, str | None] = {}
                    for field, pattern in xml_re_map.items():
                        m = pattern.search(body)
                        result[field] = m.group(1).strip() if m else None
                    if any(result.values()):
                        return result
                except Exception:
                    continue
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 4. mDNS / DNS-SD unicast service browse
# ─────────────────────────────────────────────────────────────────────────────

# Service types to query — ordered by fingerprinting specificity
_MDNS_SERVICE_TYPES = [
    "_apple-mobdev2._tcp.local.",  # iPhone / iPad (Apple Mobile Device v2)
    "_device-info._tcp.local.",  # Apple device model info
    "_androidtvremote2._tcp.local.",  # Android TV
    "_googlecast._tcp.local.",  # Chromecast / Google Home / Android
    "_airplay._tcp.local.",  # Apple TV / HomePod / AirPlay speaker
    "_appletv-v2._tcp.local.",  # Apple TV (older protocol)
    "_ipp._tcp.local.",  # IPP printers
    "_pdl-datastream._tcp.local.",  # PCL/PostScript printers
    "_printer._tcp.local.",  # Generic printers
    "_rtsp._tcp.local.",  # IP cameras (RTSP stream)
    "_smb._tcp.local.",  # SMB / NAS / Windows
    "_afpovertcp._tcp.local.",  # AFP / Mac file sharing (NAS / Mac)
    "_ssh._tcp.local.",  # Linux / Mac SSH
    "_workstation._tcp.local.",  # Linux / Mac Avahi workstation
    "_rfb._tcp.local.",  # VNC / Apple Screen Sharing
    "_sip._tcp.local.",  # VoIP phone
    "_http._tcp.local.",  # Generic HTTP (IoT, routers)
]

# Map service type → device type hint
_MDNS_SERVICE_TO_DEVICE: dict[str, str] = {
    "_apple-mobdev2._tcp.local.": "ios_device",
    "_device-info._tcp.local.": "ios_device",
    "_androidtvremote2._tcp.local.": "android_device",
    "_googlecast._tcp.local.": "chromecast",
    "_airplay._tcp.local.": "apple_tv",
    "_appletv-v2._tcp.local.": "apple_tv",
    "_ipp._tcp.local.": "printer",
    "_pdl-datastream._tcp.local.": "printer",
    "_printer._tcp.local.": "printer",
    "_rtsp._tcp.local.": "ip_camera",
    "_smb._tcp.local.": "nas",
    "_afpovertcp._tcp.local.": "nas",
    "_sip._tcp.local.": "voip_phone",
}


async def _run_mdns_probe(ip: str) -> dict[str, Any]:
    """Query mDNS service records for a specific IP using zeroconf.

    Returns ``{hostname, services, device_type_hint, os_hint}``.
    Skips silently if zeroconf is not installed.
    """
    if not _ZEROCONF_AVAILABLE:
        return {}

    # We use the listener pattern with a short timeout
    found_services: list[str] = []
    hostname_from_mdns: str | None = None
    os_hint: str | None = None
    device_hint: str | None = None

    try:
        from zeroconf import ServiceInfo
        from zeroconf.asyncio import AsyncZeroconf

        aiozc = AsyncZeroconf()
        try:

            async def _query_one(stype: str) -> tuple[str, ServiceInfo | None]:
                name_to_probe = f"{ip.replace('.', '-')}.{stype}"
                try:
                    return stype, await asyncio.wait_for(
                        aiozc.async_get_service_info(stype, name_to_probe),
                        timeout=0.5,
                    )
                except Exception:
                    return stype, None

            gathered = await asyncio.gather(
                *[_query_one(stype) for stype in _MDNS_SERVICE_TYPES],
                return_exceptions=True,
            )
            for _entry in gathered:
                if isinstance(_entry, BaseException):
                    continue
                _stype, _info = _entry
                if _info is None:
                    continue
                found_services.append(_stype)
                if not hostname_from_mdns and _info.server:
                    hostname_from_mdns = _info.server.rstrip(".")
                if _info.properties:
                    _props = {
                        k.decode("utf-8", errors="replace") if isinstance(k, bytes) else k: (
                            v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v
                        )
                        for k, v in _info.properties.items()
                    }
                    if "model" in _props:
                        _model: str = _props["model"] or ""
                        if _model.startswith(("iPhone", "iPad", "iPod")):
                            device_hint = "ios_device"
                            os_hint = "iOS"
                        elif _model.startswith("AppleTV"):
                            device_hint = "apple_tv"
                            os_hint = "tvOS"
                    if "osName" in _props:
                        os_hint = _props["osName"]
                if not device_hint:
                    device_hint = _MDNS_SERVICE_TO_DEVICE.get(_stype)
        finally:
            await aiozc.async_close()
    except Exception as e:
        logger.debug("mDNS probe setup failed for %s: %s", ip, e)
        return {}

    return {
        "hostname": hostname_from_mdns,
        "services": found_services,
        "device_type_hint": device_hint,
        "os_hint": os_hint,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. TCP banner parse
# ─────────────────────────────────────────────────────────────────────────────

# Each entry: (regex_pattern, result_dict).  First match wins within a port group.
_BANNER_RULES: list[tuple[re.Pattern[str], dict[str, str | None]]] = [
    # SSH banners ─────────────────────────────────────────────────────────────
    (
        re.compile(r"SSH-\d+\.\d+-OpenSSH[_/]for_Windows", re.I),
        {"os_family": "Windows", "os_vendor": "Microsoft", "device_type": "windows_pc"},
    ),
    (re.compile(r"SSH-\d+\.\d+.*Debian", re.I), {"os_family": "Linux", "os_vendor": "Debian"}),
    (re.compile(r"SSH-\d+\.\d+.*Ubuntu", re.I), {"os_family": "Linux", "os_vendor": "Ubuntu"}),
    (
        re.compile(r"SSH-\d+\.\d+.*CentOS|SSH-\d+\.\d+.*RedHat|SSH-\d+\.\d+.*RHEL", re.I),
        {"os_family": "Linux", "os_vendor": "Red Hat"},
    ),
    (re.compile(r"SSH-\d+\.\d+.*Alpine", re.I), {"os_family": "Linux", "os_vendor": "Alpine"}),
    (re.compile(r"SSH-\d+\.\d+.*FreeBSD", re.I), {"os_family": "BSD", "os_vendor": "FreeBSD"}),
    (re.compile(r"SSH-\d+\.\d+.*NetBSD", re.I), {"os_family": "BSD", "os_vendor": "NetBSD"}),
    (re.compile(r"SSH-\d+\.\d+.*OpenBSD", re.I), {"os_family": "BSD", "os_vendor": "OpenBSD"}),
    # RouterOS / MikroTik
    (
        re.compile(r"SSH-\d+\.\d+.*(ROSSSH|RouterOS)", re.I),
        {"os_family": "RouterOS", "os_vendor": "MikroTik", "device_type": "router"},
    ),
    # Cisco / Arista / Juniper
    (re.compile(r"SSH-\d+\.\d+.*Cisco", re.I), {"os_vendor": "Cisco", "device_type": "router"}),
    (
        re.compile(r"User Access Verification|Cisco IOS", re.I),
        {"os_vendor": "Cisco", "device_type": "router"},
    ),
    (re.compile(r"SSH-\d+\.\d+.*Arista", re.I), {"os_vendor": "Arista", "device_type": "switch"}),
    (
        re.compile(r"SSH-\d+\.\d+.*Juniper|SSH-\d+\.\d+.*JUNOS", re.I),
        {"os_vendor": "Juniper", "device_type": "router"},
    ),
    # Ubiquiti
    (
        re.compile(r"SSH-\d+\.\d+.*Ubiquiti|SSH-\d+\.\d+.*UniFi|SSH-\d+\.\d+.*AirOS", re.I),
        {"os_vendor": "Ubiquiti", "device_type": "access_point"},
    ),
    # DD-WRT / OpenWrt / Tomato
    (
        re.compile(r"SSH-\d+\.\d+.*(DD-WRT|OpenWrt|Tomato)", re.I),
        {"os_family": "Linux", "device_type": "router"},
    ),
    # Generic Linux SSH
    (re.compile(r"SSH-\d+\.\d+-OpenSSH", re.I), {"os_family": "Linux"}),
    # FTP banners ──────────────────────────────────────────────────────────────
    (re.compile(r"220.*Microsoft FTP", re.I), {"os_family": "Windows", "os_vendor": "Microsoft"}),
    (re.compile(r"220.*ProFTPD.*Debian", re.I), {"os_family": "Linux", "os_vendor": "Debian"}),
    (re.compile(r"220.*ProFTPD.*Ubuntu", re.I), {"os_family": "Linux", "os_vendor": "Ubuntu"}),
    (re.compile(r"220.*Pure-FTPd", re.I), {"os_family": "Linux"}),
    (re.compile(r"220.*vsftpd", re.I), {"os_family": "Linux"}),
    (re.compile(r"220.*Synology", re.I), {"os_vendor": "Synology", "device_type": "nas"}),
    (re.compile(r"220.*QNAP", re.I), {"os_vendor": "QNAP", "device_type": "nas"}),
    (
        re.compile(r"220.*TrueNAS|220.*FreeNAS", re.I),
        {"os_vendor": "iXsystems", "device_type": "nas"},
    ),
    (re.compile(r"220.*WD MyCloud", re.I), {"os_vendor": "Western Digital", "device_type": "nas"}),
    # SMTP banners ─────────────────────────────────────────────────────────────
    (
        re.compile(r"220.*ESMTP.*Postfix.*Ubuntu", re.I),
        {"os_family": "Linux", "os_vendor": "Ubuntu"},
    ),
    (
        re.compile(r"220.*ESMTP.*Postfix.*Debian", re.I),
        {"os_family": "Linux", "os_vendor": "Debian"},
    ),
    (
        re.compile(r"220.*Microsoft ESMTP|220.*Exchange", re.I),
        {"os_family": "Windows", "os_vendor": "Microsoft"},
    ),
    # HTTP banners (port 80 first-line or Server header) ──────────────────────
    (
        re.compile(r"Server:\s*Microsoft-IIS", re.I),
        {"os_family": "Windows", "os_vendor": "Microsoft"},
    ),
    (re.compile(r"Server:\s*nginx.*Ubuntu", re.I), {"os_family": "Linux", "os_vendor": "Ubuntu"}),
    (re.compile(r"Server:\s*nginx.*Debian", re.I), {"os_family": "Linux", "os_vendor": "Debian"}),
    (re.compile(r"Server:\s*Apache.*Ubuntu", re.I), {"os_family": "Linux", "os_vendor": "Ubuntu"}),
    (re.compile(r"Server:\s*Apache.*Debian", re.I), {"os_family": "Linux", "os_vendor": "Debian"}),
    (re.compile(r"Server:\s*ArubaOS", re.I), {"os_vendor": "Aruba", "device_type": "access_point"}),
    (re.compile(r"Server:\s*HP.?ProCurve", re.I), {"os_vendor": "HP", "device_type": "switch"}),
    (re.compile(r"Server:\s*Axis", re.I), {"os_vendor": "Axis", "device_type": "ip_camera"}),
    (
        re.compile(r"Server:\s*Hikvision|Server:\s*DNVRS-Webs", re.I),
        {"os_vendor": "Hikvision", "device_type": "ip_camera"},
    ),
    (re.compile(r"Server:\s*Dahua", re.I), {"os_vendor": "Dahua", "device_type": "ip_camera"}),
    (re.compile(r"Server:\s*GoAhead", re.I), {"device_type": "ip_camera"}),
    # Telnet / device prompts ──────────────────────────────────────────────────
    (re.compile(r"ASUSWRT", re.I), {"os_vendor": "Asus", "device_type": "router"}),
    (re.compile(r"DD-WRT", re.I), {"device_type": "router", "os_vendor": "DD-WRT"}),
    (
        re.compile(r"OpenWrt", re.I),
        {"os_family": "Linux", "device_type": "router", "os_vendor": "OpenWrt"},
    ),
    (re.compile(r"pfSense", re.I), {"os_vendor": "Netgate", "device_type": "firewall"}),
    (re.compile(r"OPNsense", re.I), {"os_vendor": "OPNsense", "device_type": "firewall"}),
    (re.compile(r"VyOS", re.I), {"os_vendor": "VyOS", "device_type": "router"}),
    (re.compile(r"MikroTik", re.I), {"os_vendor": "MikroTik", "device_type": "router"}),
    (re.compile(r"UniFi", re.I), {"os_vendor": "Ubiquiti", "device_type": "access_point"}),
    (re.compile(r"Ubiquiti", re.I), {"os_vendor": "Ubiquiti"}),
]


def _parse_banner_for_hints(banner: str | None) -> dict[str, str | None]:
    """Parse a TCP service banner and extract os_family, os_vendor, device_type.

    Returns dict with only the fields that could be inferred.  Never raises.
    """
    if not banner:
        return {}
    for pattern, result in _BANNER_RULES:
        if pattern.search(banner):
            return dict(result)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 6. HTTP fingerprinting probe (Server header + page title)
# ─────────────────────────────────────────────────────────────────────────────

_HTTP_TITLE_RULES: list[tuple[re.Pattern[str], dict[str, str | None]]] = [
    (re.compile(r"FRITZ!Box", re.I), {"os_vendor": "AVM", "device_type": "router"}),
    (re.compile(r"Netgear|NETGEAR", re.I), {"os_vendor": "Netgear", "device_type": "router"}),
    (re.compile(r"TP.?Link", re.I), {"os_vendor": "TP-Link", "device_type": "router"}),
    (re.compile(r"D-Link|D-link", re.I), {"os_vendor": "D-Link", "device_type": "router"}),
    (re.compile(r"Asus.*Router|AiMesh", re.I), {"os_vendor": "Asus", "device_type": "router"}),
    (re.compile(r"Linksys", re.I), {"os_vendor": "Linksys", "device_type": "router"}),
    (re.compile(r"pfSense", re.I), {"os_vendor": "Netgate", "device_type": "firewall"}),
    (re.compile(r"OPNsense", re.I), {"os_vendor": "OPNsense", "device_type": "firewall"}),
    (
        re.compile(r"Synology DiskStation|Synology NAS", re.I),
        {"os_vendor": "Synology", "device_type": "nas"},
    ),
    (re.compile(r"QNAP", re.I), {"os_vendor": "QNAP", "device_type": "nas"}),
    (re.compile(r"TrueNAS|FreeNAS", re.I), {"os_vendor": "iXsystems", "device_type": "nas"}),
    (
        re.compile(r"Proxmox Virtual Environment|Proxmox VE", re.I),
        {"os_vendor": "Proxmox", "device_type": "hypervisor"},
    ),
    (
        re.compile(r"VMware ESXi|vSphere", re.I),
        {"os_vendor": "VMware", "device_type": "hypervisor"},
    ),
    (re.compile(r"Hikvision|iVMS", re.I), {"os_vendor": "Hikvision", "device_type": "ip_camera"}),
    (
        re.compile(r"Axis.*Camera|AXIS.*Communications", re.I),
        {"os_vendor": "Axis", "device_type": "ip_camera"},
    ),
    (
        re.compile(r"Samsung.*TV|SmartTV.*Samsung", re.I),
        {"os_vendor": "Samsung", "device_type": "smart_tv"},
    ),
    (re.compile(r"LG.*TV|webOS TV", re.I), {"os_vendor": "LG", "device_type": "smart_tv"}),
    (re.compile(r"Sony.*Bravia", re.I), {"os_vendor": "Sony", "device_type": "smart_tv"}),
    (re.compile(r"UniFi", re.I), {"os_vendor": "Ubiquiti", "device_type": "access_point"}),
    (re.compile(r"Mikrotik|RouterOS", re.I), {"os_vendor": "MikroTik", "device_type": "router"}),
    (re.compile(r"Pi-hole", re.I), {"os_family": "Linux", "device_type": "linux_server"}),
    (re.compile(r"Home Assistant", re.I), {"device_type": "iot_device"}),
    (
        re.compile(r"Hue Philips|Hue Bridge", re.I),
        {"os_vendor": "Philips", "device_type": "iot_device"},
    ),
]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SERVER_HEADER_RULES: list[tuple[re.Pattern[str], dict[str, str | None]]] = [
    (re.compile(r"Microsoft-IIS/(\d+)", re.I), {"os_family": "Windows", "os_vendor": "Microsoft"}),
    (re.compile(r"nginx.*Ubuntu", re.I), {"os_family": "Linux", "os_vendor": "Ubuntu"}),
    (re.compile(r"nginx.*Debian", re.I), {"os_family": "Linux", "os_vendor": "Debian"}),
    (re.compile(r"Apache.*Ubuntu", re.I), {"os_family": "Linux", "os_vendor": "Ubuntu"}),
    (re.compile(r"Apache.*Debian", re.I), {"os_family": "Linux", "os_vendor": "Debian"}),
    (re.compile(r"ArubaOS", re.I), {"os_vendor": "Aruba", "device_type": "access_point"}),
    (re.compile(r"Dahua", re.I), {"os_vendor": "Dahua", "device_type": "ip_camera"}),
    (
        re.compile(r"Hikvision|DNVRS-Webs", re.I),
        {"os_vendor": "Hikvision", "device_type": "ip_camera"},
    ),
    (re.compile(r"GoAhead", re.I), {"device_type": "ip_camera"}),
    (
        re.compile(r"Jetty.*Synology|Synology", re.I),
        {"os_vendor": "Synology", "device_type": "nas"},
    ),
    (
        re.compile(r"pve-api-daemon|Proxmox", re.I),
        {"os_vendor": "Proxmox", "device_type": "hypervisor"},
    ),
]


async def _run_http_fingerprint_probe(ip: str, open_ports: list[dict]) -> dict[str, str | None]:
    """HEAD + GET probe against HTTP/HTTPS ports.  Reads Server header and page title.

    Returns ``{os_family, os_vendor, device_type}`` if anything was inferred.
    """
    http_ports = [80, 8080, 8000, 8888, 8008]
    https_ports = [443, 8443, 8006]  # 8006 = Proxmox web UI

    open_nums = {int(p.get("port", 0)) for p in open_ports if p.get("port")}
    candidates: list[tuple[str, int]] = []
    for port in https_ports:
        if port in open_nums:
            candidates.append(("https", port))
    for port in http_ports:
        if port in open_nums:
            candidates.append(("http", port))
    if not candidates:
        return {}

    result: dict[str, str | None] = {}

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for scheme, port in candidates[:3]:  # cap at 3 attempts
            url = f"{scheme}://{ip}:{port}/"
            try:
                resp = await client.get(url)
                server_hdr = resp.headers.get("server", "")
                for pat, fields in _SERVER_HEADER_RULES:
                    if pat.search(server_hdr):
                        result.update({k: v for k, v in fields.items() if v is not None})
                        break

                # Page title scan
                ct = resp.headers.get("content-type", "")
                if "html" in ct or url.endswith("/"):
                    body = resp.text[:8192]  # only first 8 KB
                    title_m = _TITLE_RE.search(body)
                    if title_m:
                        title = title_m.group(1).strip()
                        for pat, fields in _HTTP_TITLE_RULES:
                            if pat.search(title):
                                result.update({k: v for k, v in fields.items() if v is not None})
                                break

                if result:
                    return result
            except Exception as e:
                logger.debug("HTTP fingerprint probe %s: %s", url, e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 7. Offline OUI / MAC vendor lookup
# ─────────────────────────────────────────────────────────────────────────────


async def _run_vendor_lookup_local(
    mac: str | None,
    scan_oui_cache: dict[str, dict] | None = None,
) -> tuple[str | None, dict | None]:
    """Look up MAC vendor, returning (vendor_string, kb_entry_or_None).

    Priority: scan_oui_cache (merged DB+JSON) → curated KB JSON → manuf library → API.
    Pass scan_oui_cache when calling from a scan job to avoid per-device DB queries.
    """
    if not mac:
        return None, None

    prefix = mac.upper().replace(":", "").replace("-", "")[:6]

    # 1. Scan-level merged cache (DB rows take priority over JSON for same prefix)
    if scan_oui_cache is not None:
        entry = scan_oui_cache.get(prefix)
        if entry and entry.get("vendor"):
            return entry["vendor"], entry

    # 2. Curated KB JSON (always available, no DB needed)
    kb_entry = _kb_oui_lookup(mac)
    if kb_entry and kb_entry.get("vendor"):
        return kb_entry["vendor"], kb_entry

    # 3. manuf library (offline, broad coverage — may be outdated for newer OUIs)
    if _MANUF_AVAILABLE and _MANUF_PARSER is not None:
        try:
            loop = asyncio.get_running_loop()
            vendor = await loop.run_in_executor(None, _MANUF_PARSER.get_manuf_long, mac)
            if vendor:
                return vendor[:100], None
        except Exception as e:
            logger.debug("manuf local lookup failed for %s: %s", mac, e)

    # 4. Fallback: external API (may be rate-limited during bulk scans)
    try:
        from app.services.discovery_probes import _run_vendor_lookup

        api_result = await _run_vendor_lookup(mac)
        return api_result, None
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# 8. Device classification engine
# ─────────────────────────────────────────────────────────────────────────────

# OUI vendor string → device type candidates (partial match, case-insensitive)
_OUI_DEVICE_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Apple", re.I), "ios_device"),  # refined further below
    (re.compile(r"Google", re.I), "chromecast"),  # refined further below
    (re.compile(r"Amazon", re.I), "fire_tv"),
    (re.compile(r"Samsung", re.I), "smart_tv"),
    (re.compile(r"LG Electronics", re.I), "smart_tv"),
    (re.compile(r"Sony", re.I), "smart_tv"),
    (re.compile(r"Roku", re.I), "smart_tv"),
    (re.compile(r"Raspberry Pi", re.I), "linux_server"),
    (re.compile(r"Ubiquiti|Ubnt", re.I), "access_point"),
    (re.compile(r"MikroTik", re.I), "router"),
    (re.compile(r"Cisco", re.I), "router"),
    (re.compile(r"Aruba", re.I), "access_point"),
    (re.compile(r"HP|Hewlett|Arista", re.I), "switch"),
    (re.compile(r"Netgear", re.I), "router"),
    (re.compile(r"TP-Link|TP Link", re.I), "router"),
    (re.compile(r"D-Link", re.I), "router"),
    (re.compile(r"Synology", re.I), "nas"),
    (re.compile(r"QNAP", re.I), "nas"),
    (re.compile(r"Western Digital|WD", re.I), "nas"),
    (re.compile(r"Axis", re.I), "ip_camera"),
    (re.compile(r"Hikvision", re.I), "ip_camera"),
    (re.compile(r"Dahua", re.I), "ip_camera"),
    (re.compile(r"Polycom|Yealink|Grandstream|Snom|Cisco.*VOIP", re.I), "voip_phone"),
]

# Port presence → device type confidence boosts
_PORT_DEVICE_HINTS: dict[int, tuple[str, int]] = {
    554: ("ip_camera", 30),  # RTSP
    5060: ("voip_phone", 30),  # SIP
    5061: ("voip_phone", 20),  # SIP/TLS
    9100: ("printer", 35),  # JetDirect / raw printing
    515: ("printer", 35),  # LPD
    631: ("printer", 30),  # IPP
    445: ("nas", 15),  # SMB
    2049: ("nas", 20),  # NFS
    548: ("nas", 20),  # AFP
    3389: ("windows_pc", 40),  # RDP
    5900: ("linux_server", 10),  # VNC (weak, could be anything)
    8006: ("hypervisor", 50),  # Proxmox
    8443: ("access_point", 15),  # UniFi / common AP management
    623: ("server", 30),  # IPMI / BMC
    22: ("linux_server", 5),  # SSH (very weak alone)
}


def _classify_device(evidence: dict[str, Any]) -> tuple[str | None, int]:
    """Map aggregated probe evidence to a device type and confidence score.

    Args:
        evidence: merged dict from _coalesce_host_info() with extra keys:
                  ``open_ports``   — list[dict] with port numbers
                  ``mdns_services``— list[str] mDNS service types found
                  ``ssdp_device_type`` — from SSDP XML <deviceType>
                  ``banner_device_type`` — from banner parse
                  ``http_device_type``  — from HTTP probe
                  ``oui_vendor``        — string from OUI database

    Returns:
        (device_type, confidence)  confidence 0–100
    """
    scores: dict[str, int] = {}

    def _add(dtype: str, score: int) -> None:
        scores[dtype] = scores.get(dtype, 0) + score

    # mDNS services (highest specificity)
    for svc in evidence.get("mdns_services", []):
        hint = _MDNS_SERVICE_TO_DEVICE.get(svc)
        if hint:
            _add(hint, 40)

    # mDNS device type hint (from properties)
    mdns_hint = evidence.get("mdns_device_type_hint")
    if mdns_hint:
        _add(mdns_hint, 35)

    # SSDP device type
    ssdp_dt = evidence.get("ssdp_device_type")
    if ssdp_dt:
        ssdp_low = ssdp_dt.lower()
        if "mediarenderer" in ssdp_low:
            _add("smart_tv", 25)
            _add("chromecast", 15)
        elif "mediaserver" in ssdp_low:
            _add("nas", 25)
        elif "wandevice" in ssdp_low or "internet" in ssdp_low:
            _add("router", 35)
        elif "basicdevice" in ssdp_low:
            _add("router", 10)

    ssdp_fn = evidence.get("ssdp_friendly_name", "")
    if ssdp_fn:
        for pat, hints in [
            (re.compile(r"Amazon Fire|Alexa|Echo", re.I), "fire_tv"),
            (re.compile(r"Chromecast|Google Home|Nest", re.I), "chromecast"),
            (re.compile(r"Samsung.*TV|LG.*TV|Sony.*TV", re.I), "smart_tv"),
            (re.compile(r"Roku", re.I), "smart_tv"),
            (re.compile(r"Printer|HP.*LaserJet|Epson|Canon", re.I), "printer"),
        ]:
            if pat.search(ssdp_fn):
                _add(hints, 35)
                break

    # Banner-derived device type
    banner_dt = evidence.get("banner_device_type")
    if banner_dt:
        _add(banner_dt, 30)

    # HTTP-derived device type
    http_dt = evidence.get("http_device_type")
    if http_dt:
        _add(http_dt, 30)

    # KB OUI device type (curated, high reliability)
    kb_dt = evidence.get("kb_device_type")
    if kb_dt:
        _add(kb_dt, 35)

    # Hostname pattern device type (lower confidence — hostnames are user-assigned)
    hn_dt = evidence.get("hostname_device_type")
    if hn_dt:
        _add(hn_dt, 20)

    # OUI vendor hints
    oui_vendor = evidence.get("oui_vendor") or evidence.get("os_vendor", "")
    if oui_vendor:
        for pat, dtype in _OUI_DEVICE_HINTS:
            if pat.search(oui_vendor):
                _add(dtype, 20)
                break

    # Port-based hints
    open_ports = evidence.get("open_ports", [])
    port_nums = {int(p.get("port", 0)) for p in open_ports if p.get("port")}
    for port, (dtype, score) in _PORT_DEVICE_HINTS.items():
        if port in port_nums:
            _add(dtype, score)

    # OS-based hints
    os_family = (evidence.get("os_family") or "").lower()
    if "windows" in os_family:
        _add("windows_pc", 20)
    elif "linux" in os_family:
        _add("linux_server", 10)
    elif "ios" in os_family or "iphone" in os_family.lower():
        _add("ios_device", 30)
    elif "android" in os_family:
        _add("android_device", 30)
    elif "routeros" in os_family:
        _add("router", 40)
    elif "bsd" in os_family:
        _add("linux_server", 10)

    # NetBIOS presence reinforces Windows / NAS
    if evidence.get("netbios_hostname"):
        _add("windows_pc", 15)

    # Randomized MAC heuristics (locally-administered bit set)
    mac = evidence.get("mac") or ""
    if _is_randomized_mac(mac):
        mdns_svcs = evidence.get("mdns_services", [])
        if mdns_svcs:
            # Randomized MAC + any mDNS service → strong mobile indicator
            _add("mobile_device", 45)
        ttl = evidence.get("ttl")
        if ttl is not None and 55 <= ttl <= 70:
            # TTL ≈64 (Linux/Android/iOS) → likely phone or Linux box
            _add("mobile_device", 30)
        if evidence.get("is_mobile_mdns"):
            # Saw an Apple/Android-specific service type → high confidence
            _add("mobile_device", 55)

    if not scores:
        return None, 0

    best_type = max(scores, key=lambda k: scores[k])
    confidence = min(scores[best_type], 100)
    return best_type, confidence


# ─────────────────────────────────────────────────────────────────────────────
# 9. Coalesce — priority-ordered merge of all probe results
# ─────────────────────────────────────────────────────────────────────────────


def _coalesce_host_info(
    nmap_data: dict,
    snmp_data: dict,
    mdns_data: dict,
    netbios: dict,
    ssdp_data: dict,
    banner_hints: dict,
    http_hints: dict,
    rdns_hostname: str | None,
    oui_vendor: str | None,
    open_ports: list[dict],
    kb_entry: dict | None = None,
    hostname_hints: dict | None = None,
    mac: str | None = None,
    ttl_hint: int | None = None,
) -> dict[str, Any]:
    """Priority-ordered merge of all probe results.

    Priority per field (highest → lowest):
      hostname:    nmap → SNMP sysName → mDNS → NetBIOS → rDNS PTR → SSDP friendlyName
      os_family:   nmap → banner → HTTP → SNMP sysDescr → KB/hostname hint → mDNS
      os_vendor:   nmap → SSDP → HTTP fingerprint → SNMP sysDescr → KB OUI →
                   banner → manuf/API OUI → hostname pattern
      device_type: _classify_device() scores all evidence together

    Returns a dict used to assemble the raw_results entry.
    """
    _hn = hostname_hints or {}
    snmp_hints = _parse_snmp_sysdescr(snmp_data.get("sys_descr", ""))

    def _first(*values: str | None) -> str | None:
        for v in values:
            if v and v.strip():
                return v.strip()
        return None

    hostname = _first(
        nmap_data.get("hostname"),
        snmp_data.get("sys_name"),
        mdns_data.get("hostname"),
        netbios.get("hostname"),
        rdns_hostname,
        ssdp_data.get("friendly_name"),
    )

    os_family = _first(
        nmap_data.get("os_family"),
        banner_hints.get("os_family"),
        http_hints.get("os_family"),
        snmp_hints.get("os_family"),
        kb_entry.get("os_family") if kb_entry else None,
        _hn.get("os_family"),
        mdns_data.get("os_hint"),
    )

    os_vendor = _first(
        nmap_data.get("os_vendor"),  # 1. nmap (authoritative when privileged)
        ssdp_data.get("manufacturer"),  # 2. UPnP/SSDP
        http_hints.get("os_vendor"),  # 3. HTTP fingerprint (Proxmox/Synology/VMware)
        snmp_hints.get("vendor"),  # 4. SNMP sysDescr (authoritative OS descriptor)
        kb_entry.get("vendor") if kb_entry else None,  # 5. KB OUI — curated, reliable
        banner_hints.get("os_vendor"),  # 6. SSH/service banner
        oui_vendor,  # 7. manuf/API OUI (generic, may be outdated)
        _hn.get("vendor"),  # 8. Hostname pattern (last resort)
    )

    # Aggregate evidence for device classification
    all_evidence: dict[str, Any] = {
        "mac": mac or "",
        "hostname": hostname,
        "os_family": os_family,
        "os_vendor": os_vendor,
        "open_ports": open_ports,
        "mdns_services": mdns_data.get("services", []),
        "mdns_device_type_hint": mdns_data.get("device_type_hint"),
        "is_mobile_mdns": mdns_data.get("is_mobile_mdns", False),
        "ssdp_device_type": ssdp_data.get("device_type"),
        "ssdp_friendly_name": ssdp_data.get("friendly_name"),
        "banner_device_type": banner_hints.get("device_type"),
        "http_device_type": http_hints.get("device_type"),
        "oui_vendor": oui_vendor,
        "netbios_hostname": netbios.get("hostname"),
        "kb_device_type": kb_entry.get("device_type") if kb_entry else None,
        "hostname_device_type": _hn.get("device_type"),
        "ttl": ttl_hint,
    }

    device_type, device_confidence = _classify_device(all_evidence)

    return {
        "hostname": hostname,
        "os_family": os_family,
        "os_vendor": os_vendor,
        "device_type": device_type,
        "device_confidence": device_confidence,
    }

"""Async network probe functions for discovery (nmap, ARP, SNMP, banner grab, vendor lookup)."""

import asyncio
import logging
from typing import Any

import httpx

from app.core.nmap_args import validate_nmap_arguments
from app.core.validation import validate_snmp_community
from app.services.discovery_network import PORT_SERVICE_MAP  # noqa: F401 — re-exported for callers

try:
    import nmap
except ImportError:
    nmap = None  # type: ignore[assignment]

try:
    from pysnmp.entity.engine import SnmpEngine
    from pysnmp.hlapi.v3arch.asyncio.auth import CommunityData
    from pysnmp.hlapi.v3arch.asyncio.cmdgen import get_cmd
    from pysnmp.hlapi.v3arch.asyncio.context import ContextData
    from pysnmp.hlapi.v3arch.asyncio.transport import UdpTransportTarget
    from pysnmp.smi.rfc1902 import ObjectIdentity, ObjectType

    _SNMP_AVAILABLE = True
except ImportError:
    _SNMP_AVAILABLE = False

logger = logging.getLogger(__name__)

_ARP_CAPABLE: bool | None = None
_BANNER_GRAB_TIMEOUT: float = 2.0


def _arp_available() -> bool:
    """Detect at runtime whether NET_RAW capability is available.
    Returns True only if scapy can be imported AND the process has
    sufficient privileges to open a raw socket.
    Falls back to False silently — never raises.
    """
    global _ARP_CAPABLE
    if _ARP_CAPABLE is not None:
        return _ARP_CAPABLE
    try:
        import socket

        import scapy.all  # noqa: F401

        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        s.close()
        _ARP_CAPABLE = True
    except Exception:
        _ARP_CAPABLE = False
    return _ARP_CAPABLE


async def _run_arp_scan(cidr: str) -> list[dict]:
    """Fallback mechanism if ARP capable is found."""
    if not _arp_available():
        logger.info(f"ARP not capable, skipping pure scapy ARP ping for {cidr}")
        return []

    logger.info(f"Running scapy ARP ping for {cidr}")
    try:
        from scapy.layers.l2 import ARP, Ether
        from scapy.sendrecv import srp

        ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=cidr), timeout=2, verbose=False)
        results = []
        for _snd, rcv in ans:
            results.append({"ip": rcv.psrc, "mac": rcv.hwsrc, "status": "up"})
        return results
    except Exception as e:
        logger.error(f"ARP scan failed: {e}")
        return []


def _has_raw_socket_privilege() -> bool:
    """Return True if the process can open raw sockets (root or CAP_NET_RAW)."""
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        s.close()
        return True
    except (PermissionError, OSError):
        return False


def _sanitise_nmap_args_for_unpriv(args: str) -> str:
    """Strip flags that require root when running unprivileged.

    -O (OS detection) and -sS/-sA/-sN etc. (raw SYN/ACK scans) need
    CAP_NET_RAW.  Replace with -sT (connect scan) to keep discovery working.
    Caller must pass already-validated (allowlisted) args.
    """
    import shlex

    tokens = shlex.split(args)
    filtered = [t for t in tokens if t not in ("-O", "--osscan-limit", "--osscan-guess")]
    has_scan_type = any(t.startswith("-s") and t != "-sV" for t in filtered)
    if not has_scan_type:
        filtered.insert(0, "-sT")
    else:
        filtered = ["-sT" if (t.startswith("-s") and t not in ("-sV",)) else t for t in filtered]
    return " ".join(filtered)


async def _run_nmap_scan(cidr: str, args: str) -> dict:
    if not nmap:
        logger.error("python-nmap is not installed. Unable to run scan.")
        return {}

    safe_args = validate_nmap_arguments(args)
    privileged = _has_raw_socket_privilege()
    effective_args = safe_args if privileged else _sanitise_nmap_args_for_unpriv(safe_args)
    if not privileged and effective_args != safe_args:
        logger.warning(
            "Running unprivileged — nmap args adjusted from '%s' to '%s'", safe_args, effective_args
        )

    nm = nmap.PortScanner()
    logger.info(f"Running nmap {effective_args} against {cidr}")

    # Note: We can't inject job logging here since this function doesn't have access to job/db
    # Enhanced logging will be added at the caller level

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: nm.scan(hosts=cidr, arguments=effective_args))

        results = {}
        for host in nm.all_hosts():
            host_data = nm[host]
            ip_address = host
            mac_address = None
            if "addresses" in host_data and "mac" in host_data["addresses"]:
                mac_address = host_data["addresses"]["mac"]

            hostname = None
            if "hostnames" in host_data and len(host_data["hostnames"]) > 0:
                hostname = host_data["hostnames"][0].get("name", None)

            os_family = None
            os_vendor = None
            os_accuracy = None
            if "osmatch" in host_data and len(host_data["osmatch"]) > 0:
                best_match = host_data["osmatch"][0]
                os_family = best_match.get("osclass", [{}])[0].get("osfamily", None)
                os_vendor = best_match.get("osclass", [{}])[0].get("vendor", None)
                try:
                    os_accuracy = int(best_match.get("accuracy", 0)) or None
                except (ValueError, TypeError):
                    os_accuracy = None

            open_ports = []
            if "tcp" in host_data:
                for port, port_info in host_data["tcp"].items():
                    if port_info.get("state") == "open":
                        port_name = port_info.get("name")
                        service_version = port_info.get("version", "")
                        open_ports.append(
                            {
                                "port": port,
                                "protocol": "tcp",
                                "name": port_name,
                                "version": service_version,
                            }
                        )

            # Create a clean subset of raw_xml since nm.get_nmap_last_output() could be huge
            raw_xml = ""

            results[ip_address] = {
                "mac": mac_address,
                "hostname": hostname,
                "os_family": os_family,
                "os_vendor": os_vendor,
                "os_accuracy": os_accuracy,
                "open_ports": open_ports,
                "raw": raw_xml,
            }
        return results
    except Exception as e:
        logger.error(f"Nmap scan failed: {e}")
        return {}


async def _run_snmp_probe(ip: str, community: str, version: str = "2c", port: int = 161) -> dict:
    if not community or not _SNMP_AVAILABLE:
        return {}
    try:
        community = validate_snmp_community(community)
    except ValueError:
        logger.warning("Invalid SNMP community string, skipping probe")
        return {}

    logger.info(f"Running SNMP probe for {ip}")
    result: dict[str, Any] = {"sys_name": None, "sys_descr": None, "interfaces": [], "storage": []}

    try:
        transport = await UdpTransportTarget.create((ip, port), timeout=1.0, retries=1)
        async for error_indication, error_status, _, var_binds in get_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1 if version == "2c" else 0),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity("SNMPv2-MIB", "sysName", 0)),
            ObjectType(ObjectIdentity("SNMPv2-MIB", "sysDescr", 0)),
        ):
            if error_indication or error_status:
                break
            for name, val in var_binds:
                oid_str = name.prettyPrint()
                if "sysName" in oid_str:
                    result["sys_name"] = val.prettyPrint()
                elif "sysDescr" in oid_str:
                    result["sys_descr"] = val.prettyPrint()
    except Exception as e:
        logger.debug(f"SNMP probe failed for {ip}: {e}")

    return result


async def _run_banner_grab(ip: str, ports: list[int]) -> dict[int, str]:
    """Async TCP banner grab — connects to each port and reads the first 256 bytes."""
    banners: dict[int, str] = {}
    sem = asyncio.Semaphore(10)

    async def _probe(port: int) -> None:
        async with sem:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=_BANNER_GRAB_TIMEOUT
                )
                data = await asyncio.wait_for(reader.read(512), timeout=_BANNER_GRAB_TIMEOUT)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception as e:
                    logger.debug("Discovery: writer wait_closed: %s", e, exc_info=True)
                text = data.decode(errors="replace").strip()[:256]
                if text:
                    banners[port] = text
            except Exception as e:
                logger.debug("Discovery: banner probe %s:%s failed: %s", ip, port, e, exc_info=True)

    await asyncio.gather(*[_probe(p) for p in ports[:20]])
    return banners


async def _run_vendor_lookup(mac: str) -> str | None:
    """Lookup MAC vendor via macvendors.com API.  Returns vendor string or None."""
    if not mac:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"https://api.macvendors.com/{mac}")
            if r.status_code == 200:
                return r.text.strip()[:100]
    except Exception as e:
        logger.debug("Discovery: MAC vendor lookup failed: %s", e, exc_info=True)
    return None

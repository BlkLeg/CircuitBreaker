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


def _nmap_os_capable() -> bool:
    """Return True if nmap can perform OS detection.

    Requires either root (uid 0) or cap_net_raw on the nmap binary itself.
    CAP_NET_RAW on the Python process does NOT propagate to nmap subprocesses.
    Grant with: sudo setcap cap_net_raw+eip $(which nmap)
    """
    import os
    import shutil
    import subprocess

    if os.geteuid() == 0:
        return True
    nmap_path = shutil.which("nmap")
    if not nmap_path:
        return False
    try:
        r = subprocess.run(["getcap", nmap_path], capture_output=True, text=True, timeout=2)
        return "cap_net_raw" in r.stdout
    except Exception:
        return False


async def _run_nmap_scan(cidr: str, args: str) -> dict:
    if not nmap:
        logger.error("python-nmap is not installed. Unable to run scan.")
        return {}

    safe_args = validate_nmap_arguments(args)
    effective_args = safe_args if _nmap_os_capable() else _sanitise_nmap_args_for_unpriv(safe_args)
    if effective_args != safe_args:
        logger.warning(
            "nmap lacks OS-detection privilege — args adjusted from '%s' to '%s'",
            safe_args,
            effective_args,
        )

    nm = nmap.PortScanner()
    logger.info(f"Running nmap {effective_args} against {cidr}")

    # Note: We can't inject job logging here since this function doesn't have access to job/db
    # Enhanced logging will be added at the caller level

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: nm.scan(hosts=cidr, arguments=effective_args))
    except Exception as e:
        if "root privileges" in str(e) or "QUITTING" in str(e):
            fallback_args = _sanitise_nmap_args_for_unpriv(effective_args)
            if fallback_args != effective_args:
                logger.warning(
                    "nmap OS-detection failed at runtime — retrying without -O: '%s'", fallback_args
                )
                nm = nmap.PortScanner()
                try:
                    await loop.run_in_executor(
                        None, lambda: nm.scan(hosts=cidr, arguments=fallback_args)
                    )
                except Exception as e2:
                    logger.error(f"Nmap scan failed on fallback: {e2}")
                    return {}
            else:
                logger.error(f"Nmap scan failed: {e}")
                return {}
        else:
            logger.error(f"Nmap scan failed: {e}")
            return {}

    try:
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


def _parse_lldp_neighbor_row(row: dict) -> dict:
    """Normalize a raw lldpRemTable row dict into the canonical neighbor format."""
    return {
        "local_port_desc": row.get("lldpLocPortDescr"),
        "remote_chassis_id": row.get("lldpRemChassisId"),
        "remote_port_id": row.get("lldpRemPortId"),
        "remote_port_desc": row.get("lldpRemPortDescr"),
        "remote_sys_name": row.get("lldpRemSysName"),
        "remote_mgmt_ip": row.get("lldpRemManAddr"),
        "capabilities": row.get("capabilities") or [],
    }


async def _run_lldp_probe(ip: str, community: str, port: int = 161) -> list[dict]:
    """
    Walk lldpRemTable on the target device via SNMP.
    Returns a list of neighbor dicts; empty list if device doesn't support LLDP or is unreachable.
    """
    if not community or not _SNMP_AVAILABLE:
        return []

    try:
        community = validate_snmp_community(community)
    except ValueError:
        return []

    # LLDP-MIB OIDs
    OID_LLDP_REM_CHASSIS = "1.0.8802.1.1.2.1.4.1.1.5"
    OID_LLDP_REM_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7"
    OID_LLDP_REM_PORT_DESCR = "1.0.8802.1.1.2.1.4.1.1.8"
    OID_LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
    OID_LLDP_REM_CAP = "1.0.8802.1.1.2.1.4.1.1.12"
    OID_LLDP_LOC_PORT_DESCR = "1.0.8802.1.1.2.1.3.7.1.4"

    # Capability bitmask to human-readable names
    CAP_BITS = {
        0: "other", 1: "repeater", 2: "bridge", 3: "wlanAccessPoint",
        4: "router", 5: "telephone", 6: "docsisCableDevice", 7: "stationOnly",
    }

    try:
        transport = await UdpTransportTarget.create((ip, port), timeout=2.0, retries=1)
    except Exception as e:
        logger.debug(f"LLDP probe transport failed for {ip}: {e}")
        return []

    # Collect rows indexed by (local_port_idx, rem_index)
    rows: dict[str, dict] = {}

    async def _walk_oid(oid_str: str, field: str) -> None:
        try:
            from pysnmp.hlapi.v3arch.asyncio.cmdgen import next_cmd
            async for err_ind, err_stat, _, var_binds in next_cmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                transport,
                ContextData(),
                ObjectType(ObjectIdentity(oid_str)),
                lexicographicMode=False,
            ):
                if err_ind or err_stat:
                    break
                for name, val in var_binds:
                    idx = str(name).rsplit(".", 2)[-2:]  # (localPortNum, remIndex)
                    key = ".".join(idx)
                    rows.setdefault(key, {})[field] = val.prettyPrint()
        except Exception as e:
            logger.debug(f"LLDP walk {field} failed for {ip}: {e}")

    # Walk all relevant OIDs
    await _walk_oid(OID_LLDP_REM_CHASSIS, "lldpRemChassisId")
    await _walk_oid(OID_LLDP_REM_PORT_ID, "lldpRemPortId")
    await _walk_oid(OID_LLDP_REM_PORT_DESCR, "lldpRemPortDescr")
    await _walk_oid(OID_LLDP_REM_SYS_NAME, "lldpRemSysName")
    await _walk_oid(OID_LLDP_REM_CAP, "lldpRemSysCapEnabled")
    await _walk_oid(OID_LLDP_LOC_PORT_DESCR, "lldpLocPortDescr")

    # Parse capability bitmask
    neighbors = []
    for row in rows.values():
        cap_raw = row.pop("lldpRemSysCapEnabled", "")
        caps = []
        try:
            bits = int(cap_raw)
            caps = [name for bit, name in CAP_BITS.items() if bits & (1 << bit)]
        except (ValueError, TypeError):
            pass
        row["capabilities"] = caps
        neighbors.append(_parse_lldp_neighbor_row(row))

    logger.info(f"LLDP probe {ip}: found {len(neighbors)} neighbors")
    return neighbors

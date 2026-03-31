from __future__ import annotations

import logging
import subprocess

from app.core.validation import validate_snmp_community

logger = logging.getLogger(__name__)


def _snmp_get(host: str, community: str, oid: str) -> str | None:
    try:
        r = subprocess.run(
            ["snmpget", "-v2c", "-c", community, "-Oqv", host, oid],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _snmp_walk(host: str, community: str, oid: str) -> list[str]:
    try:
        r = subprocess.run(
            ["snmpwalk", "-v2c", "-c", community, "-Oqv", host, oid],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.strip().splitlines() if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def _snmp_walk_column(host: str, community: str, oid: str) -> list[str]:
    """Walk with index output for building interface tables."""
    try:
        r = subprocess.run(
            ["snmpwalk", "-v2c", "-c", community, "-On", host, oid],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.strip().splitlines() if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


class SNMPNetworkDeviceClient:
    """
    Polls network devices (switches, routers, firewalls, APs) via SNMP.
    Collects device health (uptime, CPU, memory) and per-interface traffic.
    """

    # Device health OIDs
    OID_SYS_DESCR = ".1.3.6.1.2.1.1.1.0"
    OID_SYS_NAME = ".1.3.6.1.2.1.1.5.0"
    OID_SYS_UPTIME = ".1.3.6.1.2.1.1.3.0"

    # CPU — HOST-RESOURCES-MIB hrProcessorLoad
    OID_CPU_LOAD = ".1.3.6.1.2.1.25.3.3.1.2"

    # Memory — HOST-RESOURCES-MIB
    OID_MEM_USED = ".1.3.6.1.2.1.25.2.3.1.6"
    OID_MEM_SIZE = ".1.3.6.1.2.1.25.2.3.1.5"

    # Interface table — IF-MIB
    OID_IF_DESCR = ".1.3.6.1.2.1.2.2.1.2"
    OID_IF_OPER_STATUS = ".1.3.6.1.2.1.2.2.1.8"
    OID_IF_HC_IN = ".1.3.6.1.2.1.31.1.1.1.6"  # 64-bit preferred
    OID_IF_HC_OUT = ".1.3.6.1.2.1.31.1.1.1.10"
    OID_IF_IN = ".1.3.6.1.2.1.2.2.1.10"  # 32-bit fallback
    OID_IF_OUT = ".1.3.6.1.2.1.2.2.1.16"

    def __init__(self, host: str, community: str = "public", port: int = 161):
        self.host = host if port == 161 else f"{host}:{port}"
        try:
            self.community = validate_snmp_community(community)
        except ValueError:
            logger.warning(
                "Invalid SNMP community string for host %s, falling back to 'public'", host
            )
            self.community = "public"
        self._prev_counters: dict[str, dict[str, int]] = {}

    def poll(self) -> dict:
        result: dict = {"interfaces": [], "error": None}

        # Device health
        result["sys_name"] = _snmp_get(self.host, self.community, self.OID_SYS_NAME)
        result["sys_descr"] = _snmp_get(self.host, self.community, self.OID_SYS_DESCR)
        result["sys_uptime_ticks"] = _snmp_get(self.host, self.community, self.OID_SYS_UPTIME)

        # CPU — walk hrProcessorLoad, average all entries
        cpu_vals = _snmp_walk(self.host, self.community, self.OID_CPU_LOAD)
        if cpu_vals:
            nums = [int(v) for v in cpu_vals if v.isdigit()]
            result["cpu_percent"] = sum(nums) // len(nums) if nums else None

        # Memory — walk both tables together (paired by index)
        mem_used_lines = _snmp_walk(self.host, self.community, self.OID_MEM_USED)
        mem_size_lines = _snmp_walk(self.host, self.community, self.OID_MEM_SIZE)
        if mem_used_lines and mem_size_lines:
            total_used = sum(int(v) for v in mem_used_lines if v.isdigit())
            total_size = sum(int(v) for v in mem_size_lines if v.isdigit())
            result["memory_percent"] = round(total_used / total_size * 100) if total_size else None

        # Interfaces
        descr_lines = _snmp_walk(self.host, self.community, self.OID_IF_DESCR)
        status_lines = _snmp_walk(self.host, self.community, self.OID_IF_OPER_STATUS)
        in_lines = _snmp_walk(self.host, self.community, self.OID_IF_HC_IN) or _snmp_walk(
            self.host, self.community, self.OID_IF_IN
        )
        out_lines = _snmp_walk(self.host, self.community, self.OID_IF_HC_OUT) or _snmp_walk(
            self.host, self.community, self.OID_IF_OUT
        )

        for i, descr in enumerate(descr_lines):
            iface: dict = {"name": descr, "status": "unknown", "in_mbps": None, "out_mbps": None}

            if i < len(status_lines):
                # ifOperStatus: 1=up, 2=down, 6=notPresent
                raw_status = status_lines[i].strip()
                iface["status"] = {"1": "up", "2": "down", "6": "notPresent"}.get(
                    raw_status, "unknown"
                )

            # Rate calculation using stored previous counters
            iface_key = f"if_{i}"
            in_raw = int(in_lines[i]) if i < len(in_lines) and in_lines[i].isdigit() else None
            out_raw = int(out_lines[i]) if i < len(out_lines) and out_lines[i].isdigit() else None

            if in_raw is not None and iface_key in self._prev_counters:
                prev = self._prev_counters[iface_key]
                elapsed = prev.get("elapsed_s", 60)
                delta_in = (in_raw - prev.get("in", in_raw)) % (2**64)
                delta_out = (
                    (out_raw - prev.get("out", out_raw)) % (2**64) if out_raw is not None else 0
                )
                iface["in_mbps"] = round(delta_in * 8 / elapsed / 1_000_000, 2)
                iface["out_mbps"] = round(delta_out * 8 / elapsed / 1_000_000, 2)

            if in_raw is not None:
                self._prev_counters[iface_key] = {
                    "in": in_raw,
                    "out": out_raw or 0,
                    "elapsed_s": 60,
                }

            result["interfaces"].append(iface)

        return result

    def get_status(self, data: dict) -> str:
        if not data or data.get("error"):
            return "unknown"
        if not data.get("sys_name") and not data.get("interfaces"):
            return "unknown"
        return "healthy"

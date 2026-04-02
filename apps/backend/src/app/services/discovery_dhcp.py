"""DHCP lease snooping for mobile device discovery.

Provides a tiered fallback chain to obtain MAC→IP→hostname mappings
from the local network's DHCP server without requiring the scanner to
run as root:

  Tier 1: Parse a local dnsmasq or ISC dhcpd lease file (fastest, no auth)
  Tier 2: Parse a Pi-hole lease file
  Tier 3: SSH to a router and run a DHCP listing command

All tiers return the same normalised schema:
    [{"mac": str, "ip": str, "hostname": str|None, "expires": int|None}]

Router credentials are stored vault-encrypted (dhcp_router_user_enc /
dhcp_router_pass_enc) and decrypted here via CredentialVault.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lease file paths tried automatically (in order) when no path is configured
# ─────────────────────────────────────────────────────────────────────────────

_DNSMASQ_AUTO_PATHS = [
    "/var/lib/misc/dnsmasq.leases",
    "/var/lib/dnsmasq/dnsmasq.leases",
    "/tmp/dnsmasq.leases",
    "/etc/pihole/dhcp.leases",
]

_DHCPD_AUTO_PATHS = [
    "/var/lib/dhcpd/dhcpd.leases",
    "/var/lib/dhcp/dhcpd.leases",
    "/etc/dhcp/dhcpd.leases",
]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 / 2 — File parsers
# ─────────────────────────────────────────────────────────────────────────────


def _read_dnsmasq_leases(path: str) -> list[dict]:
    """Parse a dnsmasq lease file.

    Format (one entry per line):
        <epoch_expires> <mac> <ip> <hostname> <client-id>

    Returns [{mac, ip, hostname, expires}], skipping malformed lines.
    """
    results: list[dict] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 4:
            continue
        expires_raw, mac, ip, hostname = parts[0], parts[1], parts[2], parts[3]
        try:
            expires = int(expires_raw)
        except ValueError:
            expires = None
        results.append(
            {
                "mac": mac.upper(),
                "ip": ip,
                "hostname": hostname if hostname not in ("*", "") else None,
                "expires": expires,
            }
        )

    logger.debug("dnsmasq lease file %s: %d entries", path, len(results))
    return results


# ISC dhcpd brace-block pattern
_DHCPD_LEASE_RE = re.compile(
    r"lease\s+([\d.]+)\s*\{[^}]*?hardware\s+ethernet\s+([\w:]+);[^}]*?"
    r"(?:client-hostname\s+\"([^\"]*)\";)?[^}]*?\}",
    re.DOTALL | re.IGNORECASE,
)
_DHCPD_ENDS_RE = re.compile(r"ends\s+\d\s+(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+);")


def _read_dhcpd_leases(path: str) -> list[dict]:
    """Parse an ISC dhcpd lease file (brace-block format).

    Returns [{mac, ip, hostname, expires}].
    """
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    results: list[dict] = []
    for m in _DHCPD_LEASE_RE.finditer(content):
        ip = m.group(1)
        mac = m.group(2).upper()
        hostname = m.group(3) or None
        results.append({"mac": mac, "ip": ip, "hostname": hostname, "expires": None})

    # Deduplicate — keep latest entry per IP (dhcpd files append, latest wins)
    seen: dict[str, dict] = {}
    for entry in results:
        seen[entry["ip"]] = entry
    deduped = list(seen.values())
    logger.debug("dhcpd lease file %s: %d entries", path, len(deduped))
    return deduped


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — Router SSH
# ─────────────────────────────────────────────────────────────────────────────


async def _run_router_ssh_dhcp(
    host: str,
    username_enc: str,
    password_enc: str,
    command: str,
    timeout: float = 8.0,  # noqa: ASYNC109
) -> list[dict]:
    """SSH to a router, run a DHCP listing command, and parse the output.

    Credentials are vault-decrypted here. Uses asyncssh if available,
    falls back to subprocess ssh with StrictHostKeyChecking=no.

    The command output is parsed heuristically — it tries both dnsmasq
    lease format and common router `show` command formats.

    Returns [{mac, ip, hostname}].
    """
    try:
        from app.services.credential_vault import get_vault

        vault = get_vault()
        username = vault.decrypt(username_enc)
        password = vault.decrypt(password_enc)
    except Exception as exc:
        logger.warning("DHCP SSH: credential decryption failed: %s", exc)
        return []

    output: str | None = None

    # Try asyncssh first (preferred — pure Python, no subprocess)
    try:
        import asyncssh  # type: ignore[import-untyped]

        conn_options = asyncssh.SSHClientConnectionOptions(
            known_hosts=None,  # skip host key check for internal routers
            username=username,
            password=password,
            connect_timeout=timeout,
        )
        async with asyncssh.connect(host, options=conn_options) as conn:
            result = await asyncssh.run_command(conn, command, timeout=timeout)
            output = result.stdout
    except ImportError:
        logger.debug("asyncssh not installed; trying subprocess ssh fallback")
    except Exception as exc:
        logger.debug("asyncssh DHCP SSH to %s failed: %s", host, exc)

    # Subprocess fallback via sshpass if asyncssh unavailable/failed
    if output is None:
        import asyncio
        import shutil

        if not shutil.which("sshpass"):
            logger.warning(
                "DHCP SSH: sshpass not in PATH; subprocess fallback unavailable. "
                "Install sshpass or configure asyncssh credentials."
            )
            return []

        env_cmd = [
            "sshpass",
            "-e",
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=no",
            "-o",
            f"ConnectTimeout={int(timeout)}",
            f"{username}@{host}",
            command,
        ]
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *env_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env={**os.environ, "SSHPASS": password},
                ),
                timeout=timeout + 2,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode(errors="replace")
        except Exception as exc:
            logger.debug("subprocess ssh to %s failed: %s", host, exc)
            return []

    if not output:
        return []

    # Try dnsmasq format first, then fall back to MAC/IP free-form parse
    results = _parse_ssh_output(output)
    logger.debug("DHCP SSH %s: %d entries parsed", host, len(results))
    return results


def _parse_ssh_output(text: str) -> list[dict]:
    """Heuristically parse SSH DHCP command output.

    Handles:
    - dnsmasq lease format (epoch mac ip hostname)
    - OpenWrt / ASUSWRT `cat /tmp/dhcp.leases`
    - Cisco `show ip dhcp binding` (IP/MAC in columns)
    - MikroTik `/ip dhcp-server lease print`
    """
    results: list[dict] = []

    # Pattern 1: dnsmasq-style (epoch mac ip hostname)
    _DNS_LINE = re.compile(
        r"^\d+\s+((?:[0-9a-f]{2}:){5}[0-9a-f]{2})\s+([\d.]+)\s+(\S+)",
        re.IGNORECASE,
    )
    # Pattern 2: MAC anywhere + IP anywhere on same line
    _MAC_RE = re.compile(r"((?:[0-9a-f]{2}[:\-]){5}[0-9a-f]{2})", re.IGNORECASE)
    _IP_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\b")

    for line in text.splitlines():
        m = _DNS_LINE.match(line.strip())
        if m:
            mac, ip, hostname = m.group(1), m.group(2), m.group(3)
            results.append(
                {
                    "mac": mac.upper(),
                    "ip": ip,
                    "hostname": hostname if hostname not in ("*", "") else None,
                }
            )
            continue
        # Fallback: extract first MAC + first IP from line
        mac_m = _MAC_RE.search(line)
        ip_m = _IP_RE.search(line)
        if mac_m and ip_m:
            results.append(
                {
                    "mac": mac_m.group(1).upper().replace("-", ":"),
                    "ip": ip_m.group(1),
                    "hostname": None,
                }
            )

    # Deduplicate by IP
    seen: dict[str, dict] = {}
    for entry in results:
        seen[entry["ip"]] = entry
    return list(seen.values())


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


async def run_dhcp_lease_discovery(settings: dict) -> list[dict]:
    """Run the DHCP lease discovery fallback chain.

    Args:
        settings: dict with keys:
            lease_file_path  — explicit path (empty = auto-detect)
            router_ssh_host  — router hostname/IP for SSH tier
            router_ssh_user_enc — Fernet-encrypted SSH username
            router_ssh_pass_enc — Fernet-encrypted SSH password
            router_ssh_command  — command to run on router

    Returns deduplicated [{mac, ip, hostname}] from the first tier that
    returns at least one entry.
    """
    all_entries: list[dict] = []

    # Tier 1: configured / auto-detected file
    configured_path = (settings.get("lease_file_path") or "").strip()
    if configured_path:
        paths_to_try = [configured_path]
    else:
        paths_to_try = _DNSMASQ_AUTO_PATHS

    for path in paths_to_try:
        entries = _read_dnsmasq_leases(path)
        if entries:
            all_entries.extend(entries)
            break

    # Tier 2: dhcpd files (try all auto paths, deduplicate)
    if not all_entries:
        for path in _DHCPD_AUTO_PATHS:
            entries = _read_dhcpd_leases(path)
            if entries:
                all_entries.extend(entries)
                break

    # Tier 3: Router SSH
    router_host = (settings.get("router_ssh_host") or "").strip()
    router_user_enc = settings.get("router_ssh_user_enc") or ""
    router_pass_enc = settings.get("router_ssh_pass_enc") or ""
    router_command = (
        settings.get("router_ssh_command") or "cat /var/lib/misc/dnsmasq.leases"
    ).strip()

    if not all_entries and router_host and router_user_enc and router_pass_enc:
        ssh_entries = await _run_router_ssh_dhcp(
            router_host, router_user_enc, router_pass_enc, router_command
        )
        all_entries.extend(ssh_entries)

    # Final deduplicate by IP — last entry per IP wins
    seen: dict[str, dict] = {}
    for entry in all_entries:
        ip = entry.get("ip")
        if ip:
            seen[ip] = entry

    return list(seen.values())

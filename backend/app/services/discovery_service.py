import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.time import utcnow_iso
from app.services.log_service import write_log
from app.core.ws_manager import ws_manager
from app.db.models import (
    ScanJob, ScanResult, Hardware, Service
)
from app.services.settings_service import get_or_create_settings
from app.services.credential_vault import CredentialVault
from app.schemas.discovery import ScanJobOut, ScanResultOut
from app.db.session import SessionLocal

try:
    import nmap
except ImportError:
    nmap = None

try:
    from pysnmp.hlapi.v3arch.asyncio.cmdgen import get_cmd
    from pysnmp.hlapi.v3arch.asyncio.auth import CommunityData
    from pysnmp.hlapi.v3arch.asyncio.context import ContextData
    from pysnmp.hlapi.v3arch.asyncio.transport import UdpTransportTarget
    from pysnmp.entity.engine import SnmpEngine
    from pysnmp.smi.rfc1902 import ObjectType, ObjectIdentity
    _SNMP_AVAILABLE = True
except ImportError:
    _SNMP_AVAILABLE = False

logger = logging.getLogger(__name__)

_ARP_CAPABLE: Optional[bool] = None

def _norm_mac(mac: str | None) -> str | None:
    """Normalize MAC to uppercase colon-separated format."""
    if not mac:
        return None
    cleaned = re.sub(r'[^0-9a-fA-F]', '', mac)
    if len(cleaned) != 12:
        return mac.strip().upper()
    return ':'.join(cleaned[i:i+2] for i in range(0, 12, 2)).upper()


PORT_SERVICE_MAP = {
    80: {"name": "HTTP", "type": "web_server"},
    443: {"name": "HTTPS", "type": "web_server"},
    8006: {"name": "Proxmox", "type": "hypervisor"},
    8060: {"name": "TrueNAS", "type": "storage_appliance"},
    22: {"name": "SSH", "type": "remote_access"},
    3389: {"name": "RDP", "type": "remote_access"},
    161: {"name": "SNMP", "type": "monitoring"},
    8443: {"name": "UniFi", "type": "controller"},
    623: {"name": "IPMI", "type": "out_of_band"},
}

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
        import scapy.all  # noqa: F401
        import socket
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        s.close()
        _ARP_CAPABLE = True
    except Exception:
        _ARP_CAPABLE = False
    return _ARP_CAPABLE

async def _emit_ws_event(event_type: str, payload: dict):
    await ws_manager.broadcast({"type": event_type, **payload})

def _validate_cidr(cidr: str) -> str:
    """Validate and normalise a CIDR string.
    Raises ValueError with a clear message on any invalid input or /0.
    Never passes unvalidated strings to nmap or any subprocess.
    Returns the normalised CIDR string on success.
    """
    import ipaddress
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        if net.prefixlen == 0:
            raise ValueError("Prefix length /0 is not allowed")
        return str(net)
    except ValueError as exc:
        raise ValueError(
            f"'{cidr}' is not a valid CIDR range. Example: '192.168.1.0/24'"
        ) from exc

def _decrypt_community(encrypted: Optional[str]) -> str:
    if not encrypted:
        return ""
    vault = CredentialVault()
    return vault.decrypt(encrypted) or ""

async def _update_job_progress(
    db: Session,
    job: ScanJob,
    phase: str,
    message: str = "",
    percent: Optional[int] = None,
    processed: Optional[int] = None,
    total: Optional[int] = None,
) -> None:
    """Persist progress phase in DB and push a job_progress WebSocket event."""
    job.progress_phase = phase
    job.progress_message = message
    db.commit()
    payload = {
        "job_id": job.id,
        "phase": phase,
        "message": message,
    }
    if percent is not None:
        payload["percent"] = max(0, min(100, int(percent)))
    if processed is not None:
        payload["processed"] = processed
    if total is not None:
        payload["total"] = total
    await _emit_ws_event("job_progress", payload)


_NMAP_OVERRIDE_PREFIX = "__nmap_override__:"

def create_scan_job(db: Session, target_cidr: str, scan_types: list[str],
                    profile_id: Optional[int] = None, label: Optional[str] = None,
                    nmap_arguments: Optional[str] = None,
                    triggered_by: str = "api") -> ScanJob:
    # Raises ValueError on invalid CIDR — caller (router) converts to HTTP 422
    normalised_cidr = _validate_cidr(target_cidr)

    # B12: encode ad-hoc nmap override into the label field so run_scan_job
    # can recover it without a new DB column. Format: "__nmap_override__:<args>"
    stored_label = label
    if nmap_arguments:
        stored_label = f"{_NMAP_OVERRIDE_PREFIX}{nmap_arguments}"

    job = ScanJob(
        profile_id=profile_id,
        label=stored_label,
        target_cidr=normalised_cidr,
        scan_types_json=json.dumps(scan_types),
        status="queued",
        triggered_by=triggered_by,
        created_at=utcnow_iso()
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

async def _run_arp_scan(cidr: str) -> list[dict]:
    """Fallback mechanism if ARP capable is found."""
    if not _arp_available():
        logger.info(f"ARP not capable, skipping pure scapy ARP ping for {cidr}")
        return []
    
    logger.info(f"Running scapy ARP ping for {cidr}")
    try:
        from scapy.layers.l2 import ARP, Ether
        from scapy.sendrecv import srp
        ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=cidr), timeout=2, verbose=False)
        results = []
        for snd, rcv in ans:
            results.append({
                "ip": rcv.psrc,
                "mac": rcv.hwsrc,
                "status": "up"
            })
        return results
    except Exception as e:
        logger.error(f"ARP scan failed: {e}")
        return []

async def _run_nmap_scan(cidr: str, args: str) -> dict:
    if not nmap:
        logger.error("python-nmap is not installed. Unable to run scan.")
        return {}
    
    nm = nmap.PortScanner()
    logger.info(f"Running nmap - {args} against {cidr}")
    
    # Run in thread so we don't block asyncio event loop
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: nm.scan(hosts=cidr, arguments=args))
        
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
            if "osmatch" in host_data and len(host_data["osmatch"]) > 0:
                os_family = host_data["osmatch"][0].get('osclass', [{}])[0].get('osfamily', None)
                os_vendor = host_data["osmatch"][0].get('osclass', [{}])[0].get('vendor', None)
                
            open_ports = []
            if "tcp" in host_data:
                for port, port_info in host_data["tcp"].items():
                    if port_info.get("state") == "open":
                        port_name = port_info.get("name")
                        service_version = port_info.get("version", "")
                        open_ports.append({
                            "port": port,
                            "protocol": "tcp",
                            "name": port_name,
                            "version": service_version
                        })
                        
            # Create a clean subset of raw_xml since nm.get_nmap_last_output() could be huge
            raw_xml = ""
            
            results[ip_address] = {
                "mac": mac_address,
                "hostname": hostname,
                "os_family": os_family,
                "os_vendor": os_vendor,
                "open_ports": open_ports,
                "raw": raw_xml
            }
        return results
    except Exception as e:
        logger.error(f"Nmap scan failed: {e}")
        return {}

async def _run_snmp_probe(ip: str, community: str, version: str = "2c", port: int = 161) -> dict:
    if not community or not _SNMP_AVAILABLE:
        return {}

    logger.info(f"Running SNMP probe for {ip}")
    result = {"sys_name": None, "sys_descr": None, "interfaces": [], "storage": []}

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

async def run_scan_job(job_id: int):
    """
    Background worker function that performs the actual network scanning orchestration.
    """
    logger.info(f"Starting execution of Discovery Job {job_id}")
    
    # 1. Fetch Job and Settings
    db = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if not job:
            return
            
        settings = get_or_create_settings(db)
        scan_types = json.loads(job.scan_types_json)
        
        job.status = "running"
        job.started_at = utcnow_iso()
        db.commit()

        write_log(
            db,
            action="scan_triggered",
            entity_type="scan_job",
            entity_id=job.id,
            category="discovery",
            details=json.dumps({"cidr": job.target_cidr, "scan_types": scan_types, "triggered_by": job.triggered_by}),
        )

        # Determine effective parameters from profile or settings
        nmap_args = settings.discovery_nmap_args
        snmp_community_plain = _decrypt_community(settings.discovery_snmp_community)
        snmp_version = "2c"
        snmp_port = 161
        http_probe = settings.discovery_http_probe
        auto_merge = settings.discovery_auto_merge

        # B12: check for ad-hoc nmap override encoded in the label field
        if job.label and job.label.startswith(_NMAP_OVERRIDE_PREFIX):
            nmap_args = job.label[len(_NMAP_OVERRIDE_PREFIX):]

        if job.profile_id:
            from app.db.models import DiscoveryProfile
            profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == job.profile_id).first()
            if profile:
                if profile.nmap_arguments:
                    nmap_args = profile.nmap_arguments
                if profile.snmp_community_encrypted:
                    snmp_community_plain = _decrypt_community(profile.snmp_community_encrypted)
                if profile.snmp_version:
                    snmp_version = profile.snmp_version
                if profile.snmp_port:
                    snmp_port = profile.snmp_port
                    
        await _emit_ws_event("job_update", {"job": ScanJobOut.model_validate(job).model_dump()})
        await _emit_ws_event("job_progress", {"job_id": job.id, "message": f"Starting scan on {job.target_cidr}"})
        
        hosts_found = 0
        
        # 2 & 3. Phases 1 and 2: ARP and NMAP in parallel
        active_ips = set()
        arp_task = None
        nmap_task = None
        
        async def _arp_phase():
            if "arp" in scan_types and _arp_available():
                await _update_job_progress(db, job, "arp", "Running ARP discovery...", percent=12)
                return await _run_arp_scan(job.target_cidr)
            return []

        async def _nmap_phase():
            if "nmap" in scan_types:
                await _update_job_progress(db, job, "nmap", "Running nmap host discovery...", percent=42)
                return await _run_nmap_scan(job.target_cidr, nmap_args)
            return {}

        arp_results, nmap_results = await asyncio.gather(_arp_phase(), _nmap_phase())

        for r in arp_results:
            active_ips.add(r["ip"])
        for ip in nmap_results.keys():
            active_ips.add(ip)
                
        # 4. Phase 3 & 4: Deep Probes per IP
        n_active = len(active_ips)
        if n_active > 0 and "snmp" in scan_types and snmp_community_plain:
            await _update_job_progress(
                db,
                job,
                "snmp",
                f"Preparing deep probes for {n_active} host{'s' if n_active != 1 else ''}...",
                percent=58,
                processed=0,
                total=n_active,
            )
        elif n_active > 0 and http_probe and "http" in scan_types:
            await _update_job_progress(
                db,
                job,
                "http",
                f"Preparing HTTP probes for {n_active} host{'s' if n_active != 1 else ''}...",
                percent=58,
                processed=0,
                total=n_active,
            )

        # B6: use Python-only counters; assign to job once at the end
        hosts_found   = 0
        hosts_new     = 0
        hosts_updated = 0
        hosts_conflict = 0

        results_list = []
        for index, ip in enumerate(active_ips, start=1):
            await _emit_ws_event("job_progress", {
                "job_id": job.id,
                "phase": job.progress_phase,
                "message": f"Probing host {index}/{n_active}: {ip}",
                "processed": index - 1,
                "total": n_active,
                "percent": 58 + int(((index - 1) / max(n_active, 1)) * 35),
            })

            # Get nmap base data
            n_data = nmap_results.get(ip, {})
            mac_address = n_data.get("mac")
            hostname    = n_data.get("hostname")
            os_family   = n_data.get("os_family")
            os_vendor   = n_data.get("os_vendor")
            open_ports  = n_data.get("open_ports", [])
            raw_xml     = n_data.get("raw", "")

            snmp_data = {}
            if "snmp" in scan_types and snmp_community_plain:
                snmp_data = await _run_snmp_probe(ip, snmp_community_plain, snmp_version, snmp_port)

            # HTTP Probe fallback if hostname is empty and http requested
            if http_probe and not hostname:
                has_web = any(p["port"] in (80, 443) for p in open_ports)
                if has_web:
                    try:
                        async with httpx.AsyncClient(timeout=2.0, verify=True) as client:
                            await client.get(f"http://{ip}")
                    except Exception:
                        pass

            # Construct Result Entity
            res = ScanResult(
                scan_job_id=job.id,
                ip_address=ip,
                mac_address=mac_address,
                hostname=hostname or snmp_data.get("sys_name"),
                open_ports_json=json.dumps(open_ports) if open_ports else None,
                os_family=os_family,
                os_vendor=os_vendor,
                snmp_sys_name=snmp_data.get("sys_name"),
                snmp_sys_descr=snmp_data.get("sys_descr"),
                raw_nmap_xml=raw_xml,
                state="new",
                merge_status="pending",
                created_at=utcnow_iso()
            )
            db.add(res)

            # Match against existing hardware
            matched_hardware = None
            if mac_address:
                matched_hardware = db.query(Hardware).filter(Hardware.mac_address == mac_address).first()
            if not matched_hardware:
                matched_hardware = db.query(Hardware).filter(Hardware.ip_address == ip).first()

            if matched_hardware:
                res.matched_entity_type = "hardware"
                res.matched_entity_id   = matched_hardware.id

                # B5: Conflict detection — compare discovered vs stored fields
                conflict_fields = []
                if mac_address and matched_hardware.mac_address and \
                        mac_address.upper() != matched_hardware.mac_address.upper():
                    conflict_fields.append({
                        "field": "mac_address",
                        "stored": matched_hardware.mac_address,
                        "discovered": mac_address,
                    })
                discovered_hostname = hostname or snmp_data.get("sys_name")
                if discovered_hostname and matched_hardware.name and \
                        discovered_hostname.lower() != matched_hardware.name.lower():
                    conflict_fields.append({
                        "field": "hostname",
                        "stored": matched_hardware.name,
                        "discovered": discovered_hostname,
                    })

                if conflict_fields:
                    res.state = "conflict"
                    res.conflicts_json = json.dumps(conflict_fields)
                    hosts_conflict += 1
                else:
                    res.state = "matched"
                    hosts_updated += 1
            else:
                hosts_new += 1

            hosts_found += 1
            job.hosts_found = hosts_found
            job.hosts_new = hosts_new
            job.hosts_updated = hosts_updated
            job.hosts_conflict = hosts_conflict

            db.commit()
            db.refresh(res)

            await _emit_ws_event("result_added", {"job_id": job.id, "result": ScanResultOut.model_validate(res).model_dump()})
            results_list.append(res)

            await _emit_ws_event("job_progress", {
                "job_id": job.id,
                "phase": job.progress_phase,
                "message": f"Processed host {index}/{n_active}",
                "processed": index,
                "total": n_active,
                "percent": 58 + int((index / max(n_active, 1)) * 35),
            })

        # B3: run auto-merge BEFORE marking job completed so any exception
        # doesn't overwrite a completed job with "failed"
        if auto_merge and results_list:
            await _update_job_progress(
                db,
                job,
                "reconcile",
                f"Reconciling {hosts_found} host{'s' if hosts_found != 1 else ''}...",
                percent=95,
                processed=hosts_found,
                total=hosts_found,
            )
            for r in results_list:
                _auto_merge_result(db, r)

        # B6: assign all counters at once, then commit once
        job.hosts_found    = hosts_found
        job.hosts_new      = hosts_new
        job.hosts_updated  = hosts_updated
        job.hosts_conflict = hosts_conflict
        job.status         = "completed"
        job.completed_at   = utcnow_iso()
        db.commit()

        write_log(
            db,
            action="scan_completed",
            entity_type="scan_job",
            entity_id=job.id,
            category="discovery",
            details=json.dumps({
                "hosts_found": hosts_found,
                "hosts_new": hosts_new,
                "hosts_conflict": hosts_conflict,
                "cidr": job.target_cidr,
            }),
        )

        await _update_job_progress(
            db,
            job,
            "done",
            f"Scan complete. Found {hosts_found} host{'s' if hosts_found != 1 else ''}.",
            percent=100,
            processed=hosts_found,
            total=max(hosts_found, n_active),
        )
        await _emit_ws_event("job_update", {"job": ScanJobOut.model_validate(job).model_dump()})

    except Exception as e:
        logger.error(f"Scan job {job_id} failed: {e}")
        if 'job' in locals() and job:
            job.status = "failed"
            job.error_text = str(e)
            job.completed_at = utcnow_iso()
            job.progress_phase = "failed"
            job.progress_message = str(e)
            db.commit()
            write_log(
                db,
                action="scan_failed",
                entity_type="scan_job",
                entity_id=job.id,
                category="discovery",
                severity="error",
                details=json.dumps({"error": str(e), "cidr": job.target_cidr}),
            )
            task1 = asyncio.create_task(_emit_ws_event("job_update", {"job": ScanJobOut.model_validate(job).model_dump()}))
            task2 = asyncio.create_task(_emit_ws_event("job_progress", {"job_id": job.id, "phase": "failed", "message": str(e), "percent": 100}))
    finally:
        db.close()


def _auto_merge_result(db: Session, result: ScanResult):
    """
    Attempt to automatically merge a scan result into the system without manual intervention.
    Called when discovery_auto_merge is true, or via API bulk action.
    """
    if result.merge_status != "pending":
        return
        
    now = utcnow_iso()
    
    # Update existing match
    if result.state == "matched" and result.matched_entity_type == "hardware":
        hw = db.query(Hardware).filter(Hardware.id == result.matched_entity_id).first()
        if hw:
            # Update last_seen
            hw.last_seen = now
            hw.status = "online"
            # Supplement missing info
            if not hw.mac_address and result.mac_address:
                hw.mac_address = result.mac_address
            if not hw.os_version and result.os_family:
                hw.os_version = result.os_family
            db.commit()
            
            result.merge_status = "merged"
            db.commit()
            return
            
    # Create new entity
    if result.state == "new":
        # Create a new piece of hardware
        name = result.hostname or result.snmp_sys_name or f"Discovered Host - {result.ip_address}"
        # Determine hardware role based on OS or ports (heuristics)
        # For simplicity, default to server.
        hw = Hardware(
            name=name,
            role="server",
            ip_address=result.ip_address,
            mac_address=result.mac_address,
            vendor=result.os_vendor,
            status="online",
            source="discovery",
            discovered_at=now,
            last_seen=now,
            created_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
            updated_at=datetime.fromisoformat(now) if "T" in now else datetime.now()
        )
        db.add(hw)
        db.commit()
        db.refresh(hw)
        
        # Link services based on open ports
        if result.open_ports_json:
            try:
                ports = json.loads(result.open_ports_json)
                for p in ports:
                    port_num = int(p["port"])
                    if port_num in PORT_SERVICE_MAP:
                        s_map = PORT_SERVICE_MAP[port_num]
                        svc_name = f"{s_map['name']} on {hw.name}"
                        svc = Service(
                            name=svc_name,
                            slug=_make_service_slug(db, svc_name, hw.id),
                            status="running",
                            hardware_id=hw.id,
                            ports_json=json.dumps([{
                                "port": port_num,
                                "protocol": p.get("protocol", "tcp"),
                            }]),
                        )
                        db.add(svc)
                db.commit()
            except Exception:
                pass
                
        result.matched_entity_type = "hardware"
        result.matched_entity_id = hw.id
        result.merge_status = "merged"
        db.commit()

        write_log(
            db,
            action="result_auto_merged",
            entity_type="hardware",
            entity_id=hw.id,
            category="discovery",
            details=json.dumps({"ip": result.ip_address, "source": "nmap", "scan_result_id": result.id}),
        )

# B4: The main event loop captured at import time (set by main.py lifespan).
# APScheduler jobs run in a thread pool; they must dispatch coroutines onto
# this loop with run_coroutine_threadsafe — NOT asyncio.run() — so that
# ws_manager.broadcast() reaches the live WebSocket connections.
_main_loop: Optional[asyncio.AbstractEventLoop] = None

def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from main.py lifespan startup to register the running loop."""
    global _main_loop
    _main_loop = loop


# --- Public API Functions ---

def run_scan_job_by_profile(profile_id: int):
    """Entry point for APScheduler to kick off a profile scan."""
    db = SessionLocal()
    try:
        from app.db.models import DiscoveryProfile
        profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()
        if not profile or not profile.enabled:
            return

        profile.last_run = utcnow_iso()
        db.commit()

        scan_types = json.loads(profile.scan_types)
        job = create_scan_job(
            db, target_cidr=profile.cidr, scan_types=scan_types,
            profile_id=profile.id, triggered_by="scheduler"
        )

        # B4: dispatch onto the app's main event loop so WS broadcasts work
        if _main_loop and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(run_scan_job(job.id), _main_loop)
        else:
            # Fallback for tests / CLI — creates a new loop in this thread
            asyncio.run(run_scan_job(job.id))

    finally:
        db.close()

def purge_old_scan_results():
    """Daily cron job to purge old scan results and jobs."""
    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        retention_days = settings.discovery_retention_days
        if retention_days <= 0:
            return
            
        logger.info(f"Purging discovery results older than {retention_days} days.")
        # We compute the cutoff in python, then execute standard SQL deletion.
        from datetime import timedelta, timezone as _tz
        cutoff_date = datetime.now(_tz.utc) - timedelta(days=retention_days)
        cutoff_iso = cutoff_date.isoformat() + "Z"
        
        # Delete old results
        result_count = db.query(ScanResult).filter(ScanResult.created_at < cutoff_iso).delete(synchronize_session=False)
        # Delete old jobs
        job_count = db.query(ScanJob).filter(ScanJob.created_at < cutoff_iso).delete(synchronize_session=False)
        db.commit()
        
        logger.info(f"Purged {result_count} old scan results and {job_count} old scan jobs.")
    except Exception as e:
        logger.error(f"Purger error: {e}")
    finally:
        db.close()


def _build_ports_list(open_ports_json: Optional[str]) -> list:
    """Build the ports suggestion list returned to the frontend after accepting a new host."""
    if not open_ports_json:
        return []
    try:
        ports = json.loads(open_ports_json)
    except Exception:
        return []
    result = []
    for p in ports:
        port_num = int(p.get("port", 0))
        protocol = p.get("protocol", "tcp")
        mapping = PORT_SERVICE_MAP.get(port_num)
        if mapping:
            result.append({
                "port": port_num,
                "protocol": protocol,
                "suggested_name": mapping["name"],
                "suggested_category": mapping["type"],
            })
        else:
            result.append({
                "port": port_num,
                "protocol": protocol,
                "suggested_name": p.get("name") or "Unknown",
                "suggested_category": "misc",
            })
    return result


def merge_scan_result(
    db: Session,
    result_id: int,
    action: str,
    entity_type: Optional[str] = None,
    overrides: dict = {},
    actor: str = "api",
) -> dict:
    """Accept or reject a single scan result.

    Returns:
      reject              → {'rejected': True}
      accept + matched    → {'updated': True}
      accept + new        → {'entity_type': ..., 'entity_id': ..., 'ports': [...]}
    Raises HTTP 404 if not found.
    Raises HTTP 409 if already accepted/rejected.
    """
    from fastapi import HTTPException

    result = db.query(ScanResult).filter(ScanResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Scan result not found")

    if result.merge_status not in ("pending",):
        raise HTTPException(
            status_code=409,
            detail=f"Result already has merge_status='{result.merge_status}'"
        )

    now = utcnow_iso()

    # ── reject ──────────────────────────────────────────────────────────────
    if action == "reject":
        result.merge_status = "rejected"
        result.reviewed_by = actor
        result.reviewed_at = now
        db.commit()
        write_log(
            db,
            action="result_rejected",
            entity_type="scan_result",
            entity_id=result.id,
            category="discovery",
            details=json.dumps({"ip": result.ip_address, "hostname": result.hostname}),
        )
        return {"rejected": True}

    # ── accept ───────────────────────────────────────────────────────────────
    if action == "accept":
        # CB-CASCADE-005: wrap accept branch in a savepoint for atomicity
        sp = db.begin_nested()
        try:
            # Normalize MAC before writing (CB-PATTERN-001)
            norm_mac = _norm_mac(result.mac_address)

            # conflict / matched: update existing entity with overrides
            if result.state in ("matched", "conflict") and result.matched_entity_type == "hardware":
                hw = db.query(Hardware).filter(Hardware.id == result.matched_entity_id).first()
                if hw:
                    hw.last_seen = now
                    hw.status = "online"
                    # CB-REL-001: link scan result to hardware
                    hw.source_scan_result_id = result.id
                    if not hw.mac_address and norm_mac:
                        hw.mac_address = norm_mac
                    if not hw.os_version and result.os_family:
                        hw.os_version = result.os_family
                    for k, v in overrides.items():
                        if hasattr(hw, k):
                            setattr(hw, k, v)
                    db.flush()

                result.merge_status = "accepted"
                result.reviewed_by = actor
                result.reviewed_at = now
                db.flush()
                sp.commit()
                db.commit()
                write_log(
                    db,
                    action="result_accepted",
                    entity_type=result.matched_entity_type or "hardware",
                    entity_id=result.matched_entity_id,
                    category="discovery",
                    details=json.dumps({"scan_result_id": result.id, "ip": result.ip_address, "hostname": result.hostname, "overrides": overrides}),
                )
                return {"updated": True}

            # new host: create hardware entity
            if result.state == "new":
                name = overrides.get("name") or result.hostname or result.snmp_sys_name or f"Discovered Host - {result.ip_address}"
                role = overrides.get("role") or "server"

                hw = Hardware(
                    name=name,
                    role=role,
                    ip_address=result.ip_address,
                    mac_address=norm_mac,
                    vendor=result.os_vendor,
                    status="online",
                    source="discovery",
                    discovered_at=now,
                    last_seen=now,
                    source_scan_result_id=result.id,  # CB-REL-001
                    created_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
                    updated_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
                )
                for k, v in overrides.items():
                    if hasattr(hw, k):
                        setattr(hw, k, v)
                db.add(hw)
                db.flush()

                result.matched_entity_type = "hardware"
                result.matched_entity_id = hw.id
                result.merge_status = "accepted"
                result.reviewed_by = actor
                result.reviewed_at = now
                db.flush()
                sp.commit()
                db.commit()
                db.refresh(hw)

                write_log(
                    db,
                    action="result_accepted",
                    entity_type="hardware",
                    entity_id=hw.id,
                    category="discovery",
                    details=json.dumps({"scan_result_id": result.id, "ip": result.ip_address, "hostname": result.hostname, "overrides": overrides}),
                )
                return {
                    "entity_type": "hardware",
                    "entity_id": hw.id,
                    "ports": _build_ports_list(result.open_ports_json),
                }

            # If we reach here inside the savepoint without matching a branch, commit savepoint
            sp.commit()
        except Exception:
            sp.rollback()
            raise

    return {"skipped": True}

def bulk_merge_results(db: Session, result_ids: list[int], action: str, actor: str = "api") -> dict:
    """Bulk accept or reject scan results.
    For bulk accept, conflict rows are skipped (they always require per-field review).
    Returns {'accepted': N, 'rejected': N, 'skipped': N}.
    """
    accepted = 0
    rejected = 0
    skipped = 0
    for rid in result_ids:
        result = db.query(ScanResult).filter(ScanResult.id == rid).first()
        if not result:
            skipped += 1
            continue
        # Conflicts must be reviewed individually on accept
        if action == "accept" and result.state == "conflict":
            skipped += 1
            continue
        try:
            merge_scan_result(db, rid, action, actor=actor)
            if action == "accept":
                accepted += 1
            else:
                rejected += 1
        except Exception as e:
            logger.error(f"Bulk merge failed for result {rid}: {e}")
            skipped += 1
    return {"accepted": accepted, "rejected": rejected, "skipped": skipped}


def enhanced_bulk_merge(db: Session, payload, actor: str = "api") -> dict:
    """Enhanced bulk merge: accept scan results + optionally create/link cluster,
    network, rack assignment, per-node overrides, and auto-create services.

    Returns summary dict with created entity counts and hardware IDs.
    """
    from app.db.models import (
        HardwareCluster, HardwareClusterMember, Network as NetworkModel,
        HardwareNetwork,
    )
    from app.services.bulk_suggest import EXTENDED_PORT_SERVICE_MAP, _parse_ports

    merged = 0
    skipped = 0
    hardware_ids = []
    created_clusters = 0
    created_networks = 0
    created_services = 0
    errors = []

    # Build per-result assignment lookup
    assignment_map = {}
    for a in (payload.assignments or []):
        assignment_map[a.result_id] = a

    # ── Step A: Cluster ──────────────────────────────────────────────────────
    cluster_id = None
    if payload.cluster:
        existing_cluster = db.query(HardwareCluster).filter(
            HardwareCluster.name == payload.cluster.name
        ).first()
        if existing_cluster:
            cluster_id = existing_cluster.id
        else:
            cluster = HardwareCluster(
                name=payload.cluster.name,
                description=payload.cluster.description,
                environment=payload.cluster.environment,
                location=payload.cluster.location,
            )
            db.add(cluster)
            db.flush()
            cluster_id = cluster.id
            created_clusters = 1

    # ── Step B: Network ──────────────────────────────────────────────────────
    network_id = None
    if payload.network:
        if payload.network.existing_id:
            network_id = payload.network.existing_id
        else:
            # Check for existing by CIDR
            if payload.network.cidr:
                existing_net = db.query(NetworkModel).filter(
                    NetworkModel.cidr == payload.network.cidr
                ).first()
                if existing_net:
                    network_id = existing_net.id
            if not network_id:
                net = NetworkModel(
                    name=payload.network.name,
                    cidr=payload.network.cidr,
                    vlan_id=payload.network.vlan_id,
                    gateway=payload.network.gateway,
                    description=payload.network.description,
                )
                db.add(net)
                db.flush()
                network_id = net.id
                created_networks = 1

    # ── Step C: Merge each result ────────────────────────────────────────────
    for rid in payload.result_ids:
        result = db.query(ScanResult).filter(ScanResult.id == rid).first()
        if not result:
            skipped += 1
            continue
        if result.state == "conflict":
            skipped += 1
            continue
        if result.merge_status != "pending":
            skipped += 1
            continue

        # Build overrides from per-node assignment
        overrides = {}
        assignment = assignment_map.get(rid)
        if assignment:
            for field in ("vendor", "vendor_catalog_key", "model_catalog_key",
                          "vendor_icon_slug", "role", "name", "rack_unit", "u_height"):
                val = getattr(assignment, field, None)
                if val is not None:
                    overrides[field] = val

        # Apply rack_id from payload-level
        if payload.rack_id:
            overrides["rack_id"] = payload.rack_id

        try:
            merge_result = merge_scan_result(
                db, rid, "accept", overrides=overrides, actor=actor
            )
        except Exception as e:
            logger.error(f"Enhanced bulk merge failed for result {rid}: {e}")
            errors.append({"result_id": rid, "error": str(e)})
            skipped += 1
            continue

        merged += 1
        entity_id = merge_result.get("entity_id")
        if not entity_id and merge_result.get("updated"):
            # For matched results, get the hardware ID from the result
            entity_id = result.matched_entity_id

        if entity_id:
            hardware_ids.append(entity_id)

            # Link to cluster
            if cluster_id:
                existing_member = db.query(HardwareClusterMember).filter(
                    HardwareClusterMember.cluster_id == cluster_id,
                    HardwareClusterMember.hardware_id == entity_id,
                ).first()
                if not existing_member:
                    role = overrides.get("role") or (assignment.role if assignment else None)
                    member = HardwareClusterMember(
                        cluster_id=cluster_id,
                        hardware_id=entity_id,
                        role=role,
                    )
                    db.add(member)
                    db.flush()

            # Link to network
            if network_id:
                existing_link = db.query(HardwareNetwork).filter(
                    HardwareNetwork.network_id == network_id,
                    HardwareNetwork.hardware_id == entity_id,
                ).first()
                if not existing_link:
                    hw_net = HardwareNetwork(
                        network_id=network_id,
                        hardware_id=entity_id,
                        ip_address=result.ip_address,
                    )
                    db.add(hw_net)
                    db.flush()

            # Auto-create services
            if payload.create_services:
                ports = _parse_ports(result.open_ports_json)
                for p in ports:
                    port_num = int(p.get("port", 0))
                    svc_info = EXTENDED_PORT_SERVICE_MAP.get(port_num)
                    if svc_info:
                        svc_name = svc_info["name"]
                        slug = _make_service_slug(db, svc_name, entity_id)
                        svc = Service(
                            name=svc_name,
                            slug=slug,
                            hardware_id=entity_id,
                            port=port_num,
                            protocol=p.get("protocol", "tcp"),
                            status="active",
                            source="discovery",
                        )
                        db.add(svc)
                        db.flush()
                        created_services += 1

    db.commit()

    return {
        "merged": merged,
        "skipped": skipped,
        "created": {
            "clusters": created_clusters,
            "networks": created_networks,
            "services": created_services,
        },
        "hardware_ids": hardware_ids,
        "errors": errors,
    }


def _make_service_slug(db: Session, name: str, hardware_id: int) -> str:
    """Generate a unique slug for a discovery-created service.

    Derives a base slug from the service name, then appends the hardware_id
    to avoid collisions when the same port name appears on multiple hosts.
    Falls back to appending an incrementing counter if the slug still collides.
    """
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    candidate = f"{base}-hw{hardware_id}"
    # Guard against UNIQUE constraint violation
    from sqlalchemy import select as _select
    from app.db.models import Service as _Service
    counter = 1
    while db.execute(_select(_Service).where(_Service.slug == candidate)).scalar_one_or_none():
        candidate = f"{base}-hw{hardware_id}-{counter}"
        counter += 1
    return candidate

def refresh_ip_pool():
    """
    Scheduled job to refresh IP statuses in the live_metrics table.
    Checks reachability of known IP addresses and updates last_seen and status.
    """
    db = SessionLocal()
    try:
        from app.db.models import LiveMetric
        from datetime import datetime, timezone, timedelta
        
        # This is a stub for the full implementation of refresh_ip_pool
        # that handles Ping/ARP to verify host status
        metrics = db.query(LiveMetric).all()
        now = datetime.now(timezone.utc)
        
        for metric in metrics:
            if metric.last_seen and (now - metric.last_seen) > timedelta(days=1):
                metric.status = "offline"
                
        db.commit()
    except Exception as e:
        logger.error(f"Error in refresh_ip_pool: {e}")
    finally:
        db.close()


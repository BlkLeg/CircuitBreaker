import asyncio
import json
import logging
import time as _time_module
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from app.core.nmap_args import validate_nmap_arguments
from app.core.time import utcnow_iso
from app.core.ws_manager import ws_manager
from app.db.models import (
    Hardware,
    ScanJob,
    ScanLog,
    ScanResult,
)
from app.db.session import SessionLocal, get_session_context
from app.schemas.discovery import ScanResultOut
from app.services.discovery_merge import (
    _auto_merge_result,
    bulk_merge_results,  # noqa: F401
    enhanced_bulk_merge,  # noqa: F401
    merge_scan_result,  # noqa: F401
)
from app.services.discovery_network import (
    _NMAP_OVERRIDE_PREFIX,
    PORT_SERVICE_MAP,
    _decrypt_community,
    _match_ip_to_network,
    _validate_cidr,
    resolve_vlans_to_cidrs,
)
from app.services.discovery_probes import (
    _ARP_CAPABLE,  # noqa: F401
    _arp_available,
    _has_raw_socket_privilege,
    _run_arp_scan,
    _run_banner_grab,
    _run_nmap_scan,
    _run_snmp_probe,
    _run_vendor_lookup,
)
from app.services.discovery_safe import (
    docker_discover,
    is_docker_socket_available,
    scan_subnet_safe,
)
from app.services.discovery_scheduler import (
    _max_concurrent_scans,
    _running_scan_count,
    _schedule_queued_scan_jobs,
    purge_old_scan_results,  # noqa: F401
    refresh_ip_pool,  # noqa: F401
    run_scan_job_by_profile,  # noqa: F401
    set_main_loop,  # noqa: F401
)
from app.services.log_service import write_log
from app.services.settings_service import get_or_create_settings

try:
    import nmap
except ImportError:
    nmap = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


_scan_start_gate = asyncio.Lock()
_ema_eta: dict[int, float] = {}
_last_progress_snap: dict[int, tuple[float, float]] = {}

_REDIS_DISCOVERY_CHANNEL = "cb:discovery:events"


async def _emit_ws_event(event_type: str, payload: dict) -> None:
    """Broadcast a discovery event via Redis pub/sub, WebSocket, and NATS.

    Primary delivery: Redis pub/sub (crosses Uvicorn worker boundaries).
    Fallback: in-process ``ws_manager.broadcast`` when Redis is unavailable.
    NATS publish is always attempted for SSE and external consumers.
    """
    from app.core import subjects
    from app.core.nats_client import nats_client
    from app.core.redis import get_redis

    message = {"type": event_type, **payload}

    r = await get_redis()
    if r is not None:
        try:
            await r.publish(_REDIS_DISCOVERY_CHANNEL, json.dumps(message, default=str))
        except Exception as exc:
            logger.debug("Discovery Redis publish failed, falling back to local broadcast: %s", exc)
            await ws_manager.broadcast(message)
    else:
        await ws_manager.broadcast(message)

    _SUBJECT_MAP = {
        "job_progress": subjects.DISCOVERY_SCAN_PROGRESS,
        "job_update": subjects.DISCOVERY_SCAN_COMPLETED,
        "scan_log_entry": subjects.DISCOVERY_SCAN_PROGRESS,
        "result_added": subjects.DISCOVERY_DEVICE_FOUND,
        "result_processed": subjects.DISCOVERY_DEVICE_FOUND,
    }
    subject = _SUBJECT_MAP.get(event_type, subjects.NOTIFICATION_EVENT)
    await nats_client.publish(subject, {"event_type": event_type, **payload})


async def _update_job_progress(
    job_id: int,
    phase: str,
    message: str = "",
    percent: int | None = None,
    processed: int | None = None,
    total: int | None = None,
) -> None:
    """Persist progress phase in DB and push a job_progress WebSocket event."""
    started_at: str | None = None
    with get_session_context() as _db:
        _job = _db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if _job:
            _job.progress_phase = phase
            _job.progress_message = message
            started_at = _job.started_at
            _db.commit()
    payload = {
        "job_id": job_id,
        "phase": phase,
        "message": message,
    }
    if percent is not None:
        clamped = max(0, min(100, int(percent)))
        payload["percent"] = clamped
        if clamped > 0 and started_at:
            try:
                EMA_ALPHA = 0.2
                now_mono = _time_module.monotonic()
                prev_ts, prev_pct = _last_progress_snap.get(job_id, (now_mono, 0.0))
                time_delta = max(now_mono - prev_ts, 0.5)
                pct_delta = max(clamped - prev_pct, 0.0)
                if pct_delta > 0:
                    rate = pct_delta / time_delta
                    instant_eta = (100.0 - clamped) / rate
                else:
                    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    elapsed = (datetime.now(UTC) - started).total_seconds()
                    instant_eta = elapsed * (100.0 / max(clamped, 0.1) - 1) if elapsed > 0 else 0
                prev_ema = _ema_eta.get(job_id, instant_eta)
                new_ema = EMA_ALPHA * instant_eta + (1.0 - EMA_ALPHA) * prev_ema
                _ema_eta[job_id] = new_ema
                _last_progress_snap[job_id] = (now_mono, clamped)
                payload["eta_seconds"] = int(max(0, new_ema))
            except Exception as e:
                logger.debug("Discovery: ETA calculation failed: %s", e, exc_info=True)
    if processed is not None:
        payload["processed"] = processed
    if total is not None:
        payload["total"] = total
    await _emit_ws_event("job_progress", payload)


async def _log_scan_event(
    job_id: int,
    level: str,
    message: str,
    phase: str | None = None,
    details: str | None = None,
) -> None:
    """Log a detailed scan event to database and emit WebSocket event."""
    log_id: int | None = None
    created_ts: str = utcnow_iso()
    with get_session_context() as _db:
        scan_log = ScanLog(
            scan_job_id=job_id,
            level=level,
            phase=phase,
            message=message,
            details=details,
            created_at=created_ts,
        )
        _db.add(scan_log)
        _db.commit()
        _db.refresh(scan_log)
        log_id = scan_log.id
    log_payload = {
        "job_id": job_id,
        "log_id": log_id,
        "timestamp": created_ts,
        "level": level,
        "phase": phase,
        "message": message,
        "details": details,
    }
    await _emit_ws_event("scan_log_entry", log_payload)


def create_scan_job(
    db: Session,
    target_cidr: str | None = None,
    scan_types: list[str] | None = None,
    vlan_ids: list[int] | None = None,
    profile_id: int | None = None,
    label: str | None = None,
    nmap_arguments: str | None = None,
    triggered_by: str = "api",
) -> ScanJob:
    from app.core.config import settings as env_settings
    from app.core.network_acl import validate_scan_target

    app_cfg = get_or_create_settings(db)

    cidrs: list[str] = []
    network_ids: list[int] = []
    effective_scan_types = scan_types or []

    if vlan_ids:
        vlan_cidrs, n_ids = resolve_vlans_to_cidrs(db, vlan_ids)
        cidrs.extend(vlan_cidrs)
        network_ids.extend(n_ids)

    if target_cidr:
        normalised_cidr = _validate_cidr(target_cidr)
        cidrs.append(normalised_cidr)

    # Enforce air-gap mode and CIDR ACL on every non-docker target
    for c in cidrs:
        validate_scan_target(
            c,
            airgap_env=env_settings.airgap,
            airgap_db=getattr(app_cfg, "airgap_mode", False),
            allowed_networks_json=getattr(
                app_cfg,
                "scan_allowed_networks",
                '["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]',
            ),
        )

    if not cidrs and effective_scan_types != ["docker"]:
        raise ValueError("At least one CIDR range or VLAN must be targeted for scan.")

    # De-duplicate and sort CIDRs
    final_cidrs = sorted(set(cidrs))
    target_cidr_str = ",".join(final_cidrs) if final_cidrs else None

    # B12: encode ad-hoc nmap override into the label field (validated for injection)
    stored_label = label
    if nmap_arguments:
        safe_nmap = validate_nmap_arguments(nmap_arguments)
        stored_label = f"{_NMAP_OVERRIDE_PREFIX}{safe_nmap}"

    job = ScanJob(
        profile_id=profile_id,
        label=stored_label,
        target_cidr=target_cidr_str,
        vlan_ids=json.dumps(vlan_ids or []),
        network_ids=json.dumps(network_ids),
        scan_types_json=json.dumps(effective_scan_types),
        status="queued",
        triggered_by=triggered_by,
        created_at=utcnow_iso(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _scan_setup(job_id: int) -> dict | None:
    """Phase 1 (sync, runs in executor): Read job config, verify slot, mark running.
    Returns setup dict or None if the job should not run."""
    db = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if not job:
            return None
        if job.status != "queued":
            logger.debug("Skipping scan job %s because status=%s", job_id, job.status)
            return None

        running_now = _running_scan_count(db)
        settings = get_or_create_settings(db)
        max_allowed = _max_concurrent_scans(settings)
        if running_now >= max_allowed:
            logger.info(
                "Scan job %d: no slot available (running=%d, max=%d), re-queuing",
                job_id,
                running_now,
                max_allowed,
            )
            job.status = "queued"
            db.commit()
            return None

        scan_types = json.loads(job.scan_types_json)
        job.status = "running"
        job.started_at = utcnow_iso()
        db.commit()

        nmap_args = settings.discovery_nmap_args
        snmp_community_plain = _decrypt_community(settings.discovery_snmp_community)
        snmp_version = "2c"
        snmp_port = 161
        http_probe = settings.discovery_http_probe
        auto_merge = settings.discovery_auto_merge
        docker_network_types = ["bridge"]
        docker_port_scan = False
        docker_socket_path = "/var/run/docker.sock"
        effective_mode = getattr(settings, "discovery_mode", "safe")
        docker_discovery_enabled = getattr(settings, "docker_discovery_enabled", False)
        error_reason: str | None = None

        if job.label and job.label.startswith(_NMAP_OVERRIDE_PREFIX):
            nmap_args = job.label[len(_NMAP_OVERRIDE_PREFIX) :]

        if job.profile_id:
            from app.db.models import DiscoveryProfile

            profile = (
                db.query(DiscoveryProfile).filter(DiscoveryProfile.id == job.profile_id).first()
            )
            if profile:
                if profile.nmap_arguments:
                    nmap_args = profile.nmap_arguments
                if profile.snmp_community_encrypted:
                    snmp_community_plain = _decrypt_community(profile.snmp_community_encrypted)
                if profile.snmp_version:
                    snmp_version = profile.snmp_version
                if profile.snmp_port:
                    snmp_port = profile.snmp_port
                if hasattr(profile, "docker_network_types") and profile.docker_network_types:
                    try:
                        docker_network_types = (
                            json.loads(profile.docker_network_types)
                            if isinstance(profile.docker_network_types, str)
                            else profile.docker_network_types
                        )
                    except (json.JSONDecodeError, TypeError):
                        docker_network_types = ["bridge"]
                if hasattr(profile, "docker_port_scan"):
                    docker_port_scan = bool(profile.docker_port_scan)
                if hasattr(profile, "docker_socket_path") and profile.docker_socket_path:
                    docker_socket_path = profile.docker_socket_path

        return {
            "job_id": job_id,
            "target_cidr": job.target_cidr,
            "triggered_by": job.triggered_by,
            "scan_types": scan_types,
            "nmap_args": nmap_args,
            "snmp_community_plain": snmp_community_plain,
            "snmp_version": snmp_version,
            "snmp_port": snmp_port,
            "http_probe": http_probe,
            "auto_merge": auto_merge,
            "docker_discovery_enabled": docker_discovery_enabled,
            "docker_socket_path": docker_socket_path,
            "docker_network_types": docker_network_types,
            "docker_port_scan": docker_port_scan,
            "effective_mode": effective_mode,
            "error_reason": error_reason,
            "started_at": job.started_at,
            "label": job.label,
        }
    finally:
        db.close()


def _scan_import(job_id: int, setup: dict, raw_results: list[dict]) -> dict:
    """Phase 3 (sync, runs in executor): Write scan results to DB, match hardware, auto-merge.
    Each entry in raw_results is a dict with probe data. Returns stats + serialised result list."""
    db = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if not job:
            return {"stats": {}, "results": []}

        auto_merge = setup.get("auto_merge", False)
        hosts_found = 0
        hosts_new = 0
        hosts_updated = 0
        hosts_conflict = 0
        results_out: list[dict] = []

        for raw in raw_results:
            ip = raw.get("ip")
            mac_address = raw.get("mac_address")
            hostname = raw.get("hostname")
            snmp_data = raw.get("snmp_data", {})
            source = raw.get("source", "nmap")
            network_id = raw.get("network_id")
            vlan_id = raw.get("vlan_id")

            # For docker results, resolve network_id/vlan_id if not already set
            if source == "docker" and network_id is None and ip:
                network_id, vlan_id = _match_ip_to_network(db, ip)

            res = ScanResult(
                scan_job_id=job_id,
                ip_address=ip,
                mac_address=mac_address,
                hostname=hostname or snmp_data.get("sys_name"),
                open_ports_json=raw.get("open_ports_json"),
                os_family=raw.get("os_family"),
                os_vendor=raw.get("os_vendor"),
                os_accuracy=raw.get("os_accuracy"),
                banner=raw.get("banner"),
                source_type=raw.get("source_type", source),
                snmp_sys_name=snmp_data.get("sys_name"),
                snmp_sys_descr=snmp_data.get("sys_descr"),
                raw_nmap_xml=raw.get("raw_nmap_xml", ""),
                network_id=network_id,
                vlan_id=vlan_id,
                state="new",
                merge_status="pending",
                created_at=utcnow_iso(),
            )

            # docker-sourced results have os_vendor/os_family/hostname preset via override fields
            if raw.get("os_vendor_override"):
                res.os_vendor = raw["os_vendor_override"]
            if raw.get("os_family_override"):
                res.os_family = raw["os_family_override"]
            if raw.get("hostname_override"):
                res.hostname = raw["hostname_override"]

            db.add(res)

            # Match against existing hardware
            matched_hardware = None
            if mac_address:
                matched_hardware = (
                    db.query(Hardware).filter(Hardware.mac_address == mac_address).first()
                )
            if not matched_hardware and ip:
                matched_hardware = db.query(Hardware).filter(Hardware.ip_address == ip).first()

            if matched_hardware:
                res.matched_entity_type = "hardware"
                res.matched_entity_id = matched_hardware.id

                conflict_fields = []
                if (
                    mac_address
                    and matched_hardware.mac_address
                    and mac_address.upper() != matched_hardware.mac_address.upper()
                ):
                    conflict_fields.append(
                        {
                            "field": "mac_address",
                            "stored": matched_hardware.mac_address,
                            "discovered": mac_address,
                        }
                    )
                discovered_hostname = hostname or snmp_data.get("sys_name")
                if (
                    discovered_hostname
                    and matched_hardware.name
                    and discovered_hostname.lower() != matched_hardware.name.lower()
                ):
                    conflict_fields.append(
                        {
                            "field": "hostname",
                            "stored": matched_hardware.name,
                            "discovered": discovered_hostname,
                        }
                    )

                if conflict_fields:
                    res.state = "conflict"
                    res.conflicts_json = json.dumps(conflict_fields)  # type: ignore[assignment]
                    hosts_conflict += 1
                else:
                    res.state = "matched"
                    hosts_updated += 1
            else:
                hosts_new += 1

            hosts_found += 1
            db.commit()
            db.refresh(res)
            results_out.append(ScanResultOut.model_validate(res).model_dump())

        # Auto-merge
        if auto_merge:
            results_for_merge = (
                db.query(ScanResult)
                .filter(
                    ScanResult.scan_job_id == job_id,
                    ScanResult.merge_status == "pending",
                )
                .all()
            )
            for r in results_for_merge:
                _auto_merge_result(db, r, actor=setup.get("triggered_by") or "system")

        # Update job counters
        job.hosts_found = hosts_found
        job.hosts_new = hosts_new
        job.hosts_updated = hosts_updated
        job.hosts_conflict = hosts_conflict
        db.commit()

        return {
            "stats": {
                "hosts_found": hosts_found,
                "hosts_new": hosts_new,
                "hosts_updated": hosts_updated,
                "hosts_conflict": hosts_conflict,
            },
            "results": results_out,
        }
    finally:
        db.close()


def _scan_finalize(job_id: int, stats: dict, final_status: str) -> None:
    """Phase 4 (sync, runs in executor): finalize job status, write audit log, schedule queued scans."""  # noqa: E501
    db = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if not job:
            return

        hosts_found = stats.get("hosts_found", 0)
        job.hosts_found = stats.get("hosts_found", job.hosts_found or 0)
        job.hosts_new = stats.get("hosts_new", job.hosts_new or 0)
        job.hosts_updated = stats.get("hosts_updated", job.hosts_updated or 0)
        job.hosts_conflict = stats.get("hosts_conflict", job.hosts_conflict or 0)
        job.status = final_status
        job.completed_at = utcnow_iso()
        db.commit()

        if final_status == "completed":
            write_log(
                db,
                action="scan_completed",
                entity_type="scan_job",
                entity_id=job_id,
                category="discovery",
                actor=job.triggered_by,
                details=json.dumps(
                    {
                        "hosts_found": hosts_found,
                        "hosts_new": stats.get("hosts_new", 0),
                        "hosts_conflict": stats.get("hosts_conflict", 0),
                        "cidr": job.target_cidr,
                    }
                ),
            )
        elif final_status == "failed":
            error_text = stats.get("error_text", "")
            job.error_text = error_text
            job.error_reason = stats.get("error_reason", "scan_error: unknown")
            job.progress_phase = "failed"
            job.progress_message = error_text
            db.commit()
            write_log(
                db,
                action="scan_failed",
                entity_type="scan_job",
                entity_id=job_id,
                category="discovery",
                severity="error",
                actor=job.triggered_by,
                details=json.dumps({"error": error_text, "cidr": job.target_cidr}),
            )

        _schedule_queued_scan_jobs(db)
    finally:
        db.close()


async def run_scan_job(job_id: int) -> None:
    """
    Background worker function that performs the actual network scanning orchestration.

    Structured into 4 phases to avoid holding a DB session open during async network I/O:
      Phase 1 (_scan_setup)    — sync, in executor: read config, mark job running
      Phase 2                  — async: network discovery, per-host probing
      Phase 3 (_scan_import)   — sync, in executor: write results, match hardware
      Phase 4 (_scan_finalize) — sync, in executor: finalize job status
    """
    logger.info(f"Starting execution of Discovery Job {job_id}")
    loop = asyncio.get_running_loop()

    # ── Phase 1: Setup ────────────────────────────────────────────────────────
    async with _scan_start_gate:
        setup = await loop.run_in_executor(None, _scan_setup, job_id)
    if not setup:
        return

    target_cidr = setup["target_cidr"]
    triggered_by = setup.get("triggered_by") or "api"
    scan_types: list = setup["scan_types"]
    nmap_args: str = setup["nmap_args"]
    snmp_community_plain: str = setup.get("snmp_community_plain", "")
    snmp_version: str = setup.get("snmp_version", "2c")
    snmp_port: int = setup.get("snmp_port", 161)
    http_probe: bool = setup.get("http_probe", False)
    docker_discovery_enabled: bool = setup.get("docker_discovery_enabled", False)
    docker_socket_path: str = setup.get("docker_socket_path", "/var/run/docker.sock")
    docker_network_types: list = setup.get("docker_network_types", ["bridge"])
    docker_port_scan: bool = setup.get("docker_port_scan", False)
    effective_mode: str = setup.get("effective_mode", "safe")
    label: str | None = setup.get("label")

    # Publish NATS scan started event
    from app.core.nats_client import nats_client
    from app.core.subjects import DISCOVERY_SCAN_STARTED, discovery_scan_started_payload

    await nats_client.publish(
        DISCOVERY_SCAN_STARTED,
        discovery_scan_started_payload(job_id, target_cidr, triggered_by),
    )
    await _emit_ws_event(
        "job_update",
        {
            "job": {
                "id": job_id,
                "status": "running",
                "target_cidr": target_cidr,
                "triggered_by": triggered_by,
            }
        },
    )
    await _emit_ws_event(
        "job_progress", {"job_id": job_id, "message": f"Starting scan on {target_cidr}"}
    )

    raw_results: list[dict] = []

    try:
        # ── Docker-only scan (early return path) ─────────────────────────────
        if scan_types == ["docker"]:
            socket_path = "/var/run/docker.sock"
            if label and label.startswith("docker:"):
                socket_path = label[len("docker:") :]
            await _update_job_progress(
                job_id, "docker", "Enumerating Docker containers…", percent=10
            )
            await _log_scan_event(
                job_id, "INFO", f"Starting Docker discovery via {socket_path}", "docker"
            )

            containers = docker_discover(socket_path, docker_network_types, docker_port_scan)
            await _update_job_progress(
                job_id,
                "docker",
                f"{len(containers)} container(s) found — creating results…",
                percent=70,
            )

            for container in containers:
                if container.get("type") == "network_topology":
                    continue
                container_ip = container.get("ip") or None
                if container_ip is None:
                    continue
                _image = container.get("image") or "container"
                _vendor = _image.split("/")[0] if "/" in _image else _image.split(":")[0]
                raw_results.append(
                    {
                        "ip": container_ip,
                        "hostname_override": container["name"],
                        "os_vendor_override": "Docker",
                        "os_family_override": _vendor,
                        "source": "docker",
                        "source_type": "docker",
                        "raw_nmap_xml": json.dumps(
                            {
                                "source": "docker",
                                "image": _image,
                                "status": container.get("status"),
                                "container_id": container.get("container_id"),
                            }
                        ),
                        "snmp_data": {},
                        "_docker_meta": container,
                    }
                )

            import_data = await loop.run_in_executor(None, _scan_import, job_id, setup, raw_results)
            for result_data in import_data["results"]:
                await _emit_ws_event("result_added", {"job_id": job_id, "result": result_data})

            stats = import_data["stats"]
            hosts_found = stats.get("hosts_found", 0)
            await _update_job_progress(
                job_id,
                "docker",
                f"Docker scan complete. {hosts_found} container(s) discovered.",
                percent=100,
            )
            await loop.run_in_executor(None, _scan_finalize, job_id, stats, "completed")
            await _emit_ws_event("job_update", {"job": {"id": job_id, "status": "completed"}})
            _ema_eta.pop(job_id, None)
            _last_progress_snap.pop(job_id, None)
            return

        # ── Phase 2: Network Discovery ────────────────────────────────────────
        active_ips: set[str] = set()
        nmap_results: dict = {}
        arp_mac_by_ip: dict[str, str] = {}

        if effective_mode == "full" and not _has_raw_socket_privilege():
            logger.warning(
                "Job %s: discovery_mode='full' but no CAP_NET_RAW — "
                "ARP and OS detection will be skipped; nmap will run in TCP-connect mode",
                job_id,
            )
            # Do NOT downgrade to safe — nmap can still run unprivileged (-sT) and
            # resolve hostnames via DNS. Only _arp_phase and -O are skipped (handled
            # gracefully by _arp_available() and _sanitise_nmap_args_for_unpriv).

        if effective_mode == "safe":
            import ipaddress as _ipaddress

            try:
                _total_hosts = _ipaddress.IPv4Network(target_cidr, strict=False).num_addresses - 2
            except Exception:
                _total_hosts = 0
            await _update_job_progress(
                job_id,
                "ping",
                f"Pinging {max(_total_hosts, 0)} hosts in {target_cidr}…",
                percent=10,
            )
            try:
                safe_results = await loop.run_in_executor(None, scan_subnet_safe, target_cidr)
            except Exception as _scan_exc:
                logger.warning(
                    "Scan job %d: scan_subnet_safe raised %s: %s",
                    job_id,
                    type(_scan_exc).__name__,
                    _scan_exc,
                )
                safe_results = []
            await _update_job_progress(
                job_id,
                "tcp",
                (
                    f"{len(safe_results)} host"
                    f"{'s' if len(safe_results) != 1 else ''}"
                    " responded — probing TCP ports\u2026"
                ),
                percent=30,
            )
            for r in safe_results:
                ip = r["ip"]
                active_ips.add(ip)
                open_ports = [
                    {
                        "port": p,
                        "service": PORT_SERVICE_MAP.get(p, {}).get("name", "unknown"),
                        "state": "open",
                    }
                    for p in r.get("open_ports", [])
                ]
                nmap_results[ip] = {
                    "mac": None,
                    "hostname": None,
                    "os_family": None,
                    "os_vendor": None,
                    "open_ports": open_ports,
                    "raw": "",
                }
            logger.info(
                "[safe-mode] job %s: %d hosts found via ping/TCP in %s",
                job_id,
                len(active_ips),
                target_cidr,
            )
        else:

            async def _arp_phase() -> list[dict]:
                if "arp" in scan_types and _arp_available():
                    await _update_job_progress(
                        job_id, "arp", "Running ARP discovery...", percent=12
                    )
                    await _log_scan_event(job_id, "INFO", "Starting ARP discovery phase", "arp")
                    try:
                        results = await _run_arp_scan(target_cidr)
                        await _log_scan_event(
                            job_id,
                            "SUCCESS",
                            f"ARP discovery completed. Found {len(results)} responding hosts",
                            "arp",
                            f"Discovered hosts: {[r['ip'] for r in results][:10]}",
                        )
                        return results
                    except Exception as e:
                        await _log_scan_event(
                            job_id, "ERROR", f"ARP discovery failed: {str(e)}", "arp", str(e)
                        )
                        raise
                await _log_scan_event(
                    job_id, "INFO", "ARP discovery skipped (not available or not requested)", "arp"
                )
                return []

            async def _nmap_phase() -> dict:
                if "nmap" in scan_types and not nmap:
                    logger.warning(
                        "Scan job %d: python-nmap unavailable; nmap phase skipped.", job_id
                    )
                    await _log_scan_event(
                        job_id, "ERROR", "nmap tool unavailable — python-nmap not installed", "nmap"
                    )
                    return {}
                if "nmap" in scan_types:
                    await _update_job_progress(
                        job_id, "nmap", "Running nmap host discovery...", percent=42
                    )
                    await _log_scan_event(
                        job_id, "INFO", f"Starting nmap scan with args: {nmap_args}", "nmap"
                    )
                    try:
                        results = await _run_nmap_scan(target_cidr, nmap_args)
                        host_count = len(results)
                        await _log_scan_event(
                            job_id,
                            "SUCCESS",
                            f"Nmap scan completed. Discovered {host_count} active hosts",
                            "nmap",
                            f"Hosts found: {list(results.keys())[:10]}",
                        )
                        for ip, host_data in list(results.items())[:5]:
                            open_ports = host_data.get("open_ports", [])
                            hostname = host_data.get("hostname", "Unknown")
                            if open_ports:
                                port_list = [f"{p['port']}/{p['protocol']}" for p in open_ports[:5]]
                                await _log_scan_event(
                                    job_id,
                                    "INFO",
                                    f"Host {ip} ({hostname}): {len(open_ports)} open ports",
                                    "nmap",
                                    f"Ports: {', '.join(port_list)}",
                                )
                            else:
                                await _log_scan_event(
                                    job_id,
                                    "INFO",
                                    f"Host {ip} ({hostname}): No open ports detected",
                                    "nmap",
                                )
                        return results
                    except Exception as e:
                        await _log_scan_event(
                            job_id, "ERROR", f"Nmap scan failed: {str(e)}", "nmap", str(e)
                        )
                        raise
                await _log_scan_event(job_id, "INFO", "Nmap scan skipped (not requested)", "nmap")
                return {}

            arp_results, nmap_scan = await asyncio.gather(_arp_phase(), _nmap_phase())
            nmap_results = nmap_scan
            arp_mac_by_ip = {r["ip"]: r["mac"] for r in arp_results if r.get("mac")}
            for ip in arp_mac_by_ip:
                active_ips.add(ip)
            for ip in nmap_results.keys():
                active_ips.add(ip)

        # ── Per-host probing: collect raw probe data ──────────────────────────
        n_active = len(active_ips)
        if n_active > 0 and "snmp" in scan_types and snmp_community_plain:
            await _update_job_progress(
                job_id,
                "snmp",
                f"Preparing deep probes for {n_active} host{'s' if n_active != 1 else ''}...",
                percent=58,
                processed=0,
                total=n_active,
            )
            await _log_scan_event(
                job_id, "INFO", f"Starting SNMP discovery on {n_active} active hosts", "snmp"
            )
        elif n_active > 0 and http_probe and "http" in scan_types:
            await _update_job_progress(
                job_id,
                "http",
                f"Preparing HTTP probes for {n_active} host{'s' if n_active != 1 else ''}...",
                percent=58,
                processed=0,
                total=n_active,
            )

        for index, ip in enumerate(active_ips, start=1):
            await _emit_ws_event(
                "job_progress",
                {
                    "job_id": job_id,
                    "message": f"Probing host {index}/{n_active}: {ip}",
                    "processed": index - 1,
                    "total": n_active,
                    "percent": 58 + int(((index - 1) / max(n_active, 1)) * 35),
                },
            )

            n_data = nmap_results.get(ip, {})
            mac_address = n_data.get("mac") or arp_mac_by_ip.get(ip)
            hostname = n_data.get("hostname")
            os_family = n_data.get("os_family")
            os_vendor = n_data.get("os_vendor")
            os_accuracy = n_data.get("os_accuracy")
            open_ports = n_data.get("open_ports", [])
            raw_xml = n_data.get("raw", "")

            snmp_data: dict = {}
            if "snmp" in scan_types and snmp_community_plain:
                snmp_data = await _run_snmp_probe(ip, snmp_community_plain, snmp_version, snmp_port)

            if http_probe and not hostname:
                has_web = any(p["port"] in (80, 443) for p in open_ports)
                if has_web:
                    try:
                        async with httpx.AsyncClient(timeout=2.0, verify=True) as client:
                            await client.get(f"http://{ip}")
                    except Exception as e:
                        logger.debug(
                            "Discovery: HTTP probe fallback for %s: %s", ip, e, exc_info=True
                        )

            banner_text: str | None = None
            if "deep_dive" in scan_types and open_ports:
                port_nums = [p["port"] for p in open_ports if isinstance(p.get("port"), int)]
                if port_nums:
                    banners = await _run_banner_grab(ip, port_nums)
                    if banners:
                        for preferred in (22, 21, 80, 443):
                            if preferred in banners:
                                banner_text = banners[preferred]
                                break
                        if not banner_text:
                            banner_text = next(iter(banners.values()))
                if not os_vendor and mac_address:
                    os_vendor = await _run_vendor_lookup(mac_address) or os_vendor

            if "deep_dive" in scan_types:
                result_source = "deep_dive"
            elif not n_data:
                result_source = "arp"
            else:
                result_source = "nmap"

            raw_results.append(
                {
                    "ip": ip,
                    "mac_address": mac_address,
                    "hostname": hostname,
                    "os_family": os_family,
                    "os_vendor": os_vendor,
                    "os_accuracy": os_accuracy,
                    "open_ports_json": json.dumps(open_ports) if open_ports else None,
                    "raw_nmap_xml": raw_xml,
                    "banner": banner_text,
                    "source_type": result_source,
                    "snmp_data": snmp_data,
                }
            )

        # Supplemental Docker discovery
        if docker_discovery_enabled and is_docker_socket_available():
            await _update_job_progress(
                job_id, "docker", "Scanning Docker containers...", percent=94
            )
            for container in docker_discover(
                docker_socket_path, docker_network_types, docker_port_scan
            ):
                container_ip = container.get("ip") or None
                if container_ip is None:
                    continue
                _image = container.get("image") or "container"
                _vendor = _image.split("/")[0] if "/" in _image else _image.split(":")[0]
                raw_results.append(
                    {
                        "ip": container_ip,
                        "hostname_override": container["name"],
                        "os_vendor_override": "Docker",
                        "os_family_override": _vendor,
                        "source": "docker",
                        "source_type": "docker",
                        "raw_nmap_xml": json.dumps(
                            {
                                "source": "docker",
                                "image": _image,
                                "status": container.get("status"),
                                "container_id": container.get("container_id"),
                            }
                        ),
                        "snmp_data": {},
                    }
                )

        # ── Phase 3: Import results to DB ─────────────────────────────────────
        await _update_job_progress(
            job_id,
            "reconcile",
            f"Saving {len(raw_results)} result(s)…",
            percent=95,
        )
        import_data = await loop.run_in_executor(None, _scan_import, job_id, setup, raw_results)

        for result_data in import_data["results"]:
            await _emit_ws_event("result_added", {"job_id": job_id, "result": result_data})

        stats = import_data["stats"]
        hosts_found = stats.get("hosts_found", 0)

        await _update_job_progress(
            job_id,
            "done",
            f"Scan complete. Found {hosts_found} host{'s' if hosts_found != 1 else ''}.",
            percent=100,
            processed=hosts_found,
            total=max(hosts_found, n_active),
        )

        # ── Phase 4: Finalize ─────────────────────────────────────────────────
        await loop.run_in_executor(None, _scan_finalize, job_id, stats, "completed")
        await _emit_ws_event("job_update", {"job": {"id": job_id, "status": "completed"}})
        _ema_eta.pop(job_id, None)
        _last_progress_snap.pop(job_id, None)

    except Exception as e:
        logger.error(f"Scan job {job_id} failed: {e}")
        error_stats = {
            "error_text": str(e),
            "error_reason": (
                "scan_timeout"
                if isinstance(e, asyncio.TimeoutError)
                else f"scan_error: {type(e).__name__}"
            ),
        }
        await loop.run_in_executor(None, _scan_finalize, job_id, error_stats, "failed")
        await asyncio.gather(
            _emit_ws_event("job_update", {"job": {"id": job_id, "status": "failed"}}),
            _emit_ws_event(
                "job_progress",
                {"job_id": job_id, "phase": "failed", "message": str(e), "percent": 100},
            ),
            return_exceptions=True,
        )
        _ema_eta.pop(job_id, None)
        _last_progress_snap.pop(job_id, None)

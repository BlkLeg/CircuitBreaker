import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role, require_scope
from app.core.scheduler import get_scheduler
from app.core.security import require_write_auth
from app.db.models import Hardware, ListenerEvent, ScanJob, ScanLog, ScanResult, User
from app.db.session import get_db
from app.schemas.discovery import (
    AdHocScanRequest,
    BatchImportRequest,
    BulkMergeRequest,
    BulkSuggestRequest,
    DiscoveryProfileCreate,
    DiscoveryProfileOut,
    DiscoveryProfileUpdate,
    DiscoveryStatusOut,
    EnhancedBulkMergeRequest,
    MergeRequest,
    ScanJobOut,
    ScanLogOut,
    ScanResultOut,
)
from app.schemas.proxmox import ProxmoxDiscoverRunOut
from app.services import discovery_profiles_service, discovery_service
from app.services.bulk_suggest import get_vendor_catalog, suggest_bulk_actions
from app.services.discovery_safe import is_docker_socket_available
from app.services.discovery_service import _has_raw_socket_privilege
from app.services.proxmox_service import get_proxmox_discover_run, list_proxmox_discover_runs
from app.services.settings_service import get_or_create_settings

_logger = logging.getLogger(__name__)

_DEFAULT_DOCKER_SOCKET = "/var/run/docker.sock"
router = APIRouter(tags=["discovery"], dependencies=[require_scope("read", "*")])


def _get_actor(db: Session, user_id: int) -> str:
    """Return display name for audit/triggered_by; sync so it can be used in DB commits."""
    if user_id == 0:
        return "api-token"
    u = db.query(User).filter(User.id == user_id).first()
    return (u.display_name or u.email) if u else "unknown"


def _load_jobs_in_order(db: Session, job_ids: list[int]) -> list[ScanJob]:
    if not job_ids:
        return []
    rows = db.scalars(select(ScanJob).where(ScanJob.id.in_(job_ids))).all()
    rows_by_id = {row.id: row for row in rows}
    return [rows_by_id[job_id] for job_id in job_ids if job_id in rows_by_id]


def _compute_discovery_status(db: Session) -> DiscoveryStatusOut:
    settings = get_or_create_settings(db)
    discovery_enabled = getattr(settings, "discovery_enabled", False)
    scan_ack_accepted = getattr(settings, "scan_ack_accepted", False)
    discovery_mode = getattr(settings, "discovery_mode", "safe")

    pending_results = db.query(ScanResult).filter(ScanResult.merge_status == "pending").count()

    active_jobs_q = (
        db.query(ScanJob)
        .filter(ScanJob.status.in_(["queued", "running"]))
        .order_by(ScanJob.created_at.desc())
        .limit(20)
        .all()
    )
    active_jobs = [ScanJobOut.model_validate(j) for j in active_jobs_q]

    last_completed = (
        db.query(ScanJob)
        .filter(ScanJob.status == "completed")
        .order_by(ScanJob.completed_at.desc())
        .first()
    )
    raw_last_scan = getattr(last_completed, "completed_at", None)
    if isinstance(raw_last_scan, str):
        last_scan = raw_last_scan
    elif hasattr(raw_last_scan, "isoformat"):
        scan_iso = raw_last_scan.isoformat()
        last_scan = scan_iso if isinstance(scan_iso, str) else None
    else:
        last_scan = None

    next_scheduled = None
    try:
        scheduler = get_scheduler()
        earliest = None
        for job in scheduler.get_jobs():
            if job.id and job.id.startswith("discovery_profile_"):
                nrt = getattr(job, "next_run_time", None)
                if nrt is not None and (earliest is None or nrt < earliest):
                    earliest = nrt
        if earliest is not None:
            next_scheduled = (
                earliest.isoformat() if hasattr(earliest, "isoformat") else str(earliest)
            )
    except Exception:
        _logger.debug("Non-critical check failed in _compute_discovery_status", exc_info=True)

    net_raw_capable = _has_raw_socket_privilege()
    # Without CAP_NET_RAW, full mode still runs nmap (TCP-connect) for hostname/ports;
    # only ARP (MAC) and OS detection are skipped. Report as "full" since nmap runs.
    effective_mode = discovery_mode

    socket_path = getattr(settings, "docker_socket_path", None) or _DEFAULT_DOCKER_SOCKET
    docker_available = is_docker_socket_available(socket_path)

    docker_container_count = 0
    if docker_available:
        try:
            from app.services.docker_discovery import get_docker_status

            docker_container_count = get_docker_status(socket_path).get("container_count", 0)
        except Exception:
            _logger.debug("Non-critical check failed in _compute_discovery_status", exc_info=True)

    return DiscoveryStatusOut(
        discovery_enabled=discovery_enabled,
        scan_ack_accepted=scan_ack_accepted,
        pending_results=pending_results,
        active_jobs=active_jobs,
        last_scan=last_scan,
        next_scheduled=next_scheduled,
        discovery_mode=discovery_mode,
        effective_mode=effective_mode,
        net_raw_capable=net_raw_capable,
        docker_available=docker_available,
        docker_container_count=docker_container_count,
    )


@router.get("/status", response_model=DiscoveryStatusOut)
async def get_discovery_status(db: Session = Depends(get_db)):
    # Always compute fresh so docker_available reflects current socket (e.g. after compose up).
    return _compute_discovery_status(db)


# --- Profiles ---


@router.get("/profiles", response_model=list[DiscoveryProfileOut])
def get_profiles(db: Session = Depends(get_db)):
    return discovery_profiles_service.get_profiles(db)


@router.post("/profiles", response_model=DiscoveryProfileOut)
def create_profile(
    payload: DiscoveryProfileCreate,
    req: Request,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    actor = _get_actor(db, user.id)
    try:
        return discovery_profiles_service.create_profile(db, payload, actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/profiles/{profile_id}", response_model=DiscoveryProfileOut)
def update_profile(
    profile_id: int,
    payload: DiscoveryProfileUpdate,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    actor = _get_actor(db, user.id)
    try:
        return discovery_profiles_service.update_profile(db, profile_id, payload, actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: int, user: User = require_role("admin"), db: Session = Depends(get_db)
):
    actor = _get_actor(db, user.id)
    discovery_profiles_service.delete_profile(db, profile_id, actor)
    return None


@router.post("/profiles/{profile_id}/run", response_model=ScanJobOut)
@limiter.limit(lambda: get_limit("scan"))
async def run_profile_scan(
    request: Request,
    response: Response,
    profile_id: int,
    bg_tasks: BackgroundTasks,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    user_id = user.id
    profile = discovery_profiles_service.get_profile(db, profile_id)
    if not profile.enabled:
        raise HTTPException(status_code=400, detail="Profile is disabled")

    import json

    vlan_ids = []
    if profile.vlan_ids:
        try:
            vlan_ids = json.loads(profile.vlan_ids)
        except Exception:
            _logger.warning("Malformed VLAN JSON in profile %s: %s", profile.id, profile.vlan_ids)

    job = discovery_service.create_scan_job(
        db,
        target_cidr=profile.cidr,
        vlan_ids=vlan_ids,
        scan_types=json.loads(profile.scan_types),
        profile_id=profile.id,
        triggered_by=_get_actor(db, user_id),
    )

    db.expunge(job)  # Detach from session before any further commits expire attributes

    # B2: async def endpoint runs on the event loop — asyncio.create_task works here
    try:
        asyncio.create_task(discovery_service.run_scan_job(job.id))
    except Exception as exc:
        _logger.exception("Failed to schedule scan job %s", job.id)
        raise HTTPException(status_code=500, detail="Failed to start scan.") from exc
    return job


# --- Ad-Hoc ---


@router.post("/scan", response_model=ScanJobOut | list[ScanJobOut])
@limiter.limit(lambda: get_limit("scan"))
async def run_adhoc_scan(
    request: Request,
    response: Response,
    payload: AdHocScanRequest,
    bg_tasks: BackgroundTasks,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    user_id = user.id

    if payload.cidrs:
        target_list = payload.cidrs
    elif payload.cidr:
        target_list = [payload.cidr]
    else:
        target_list = []

    job_ids: list[int] = []
    try:
        for target_cidr in target_list:
            job = discovery_service.create_scan_job(
                db,
                target_cidr=target_cidr,
                vlan_ids=payload.vlan_ids,
                scan_types=payload.scan_types,
                nmap_arguments=payload.nmap_arguments,  # B12: thread through
                label=payload.label,
                triggered_by=_get_actor(db, user_id),
            )
            job_ids.append(job.id)
        if not target_list:
            # No target — create a single job with no cidr (existing behavior)
            job = discovery_service.create_scan_job(
                db,
                target_cidr=None,
                vlan_ids=payload.vlan_ids,
                scan_types=payload.scan_types,
                nmap_arguments=payload.nmap_arguments,
                label=payload.label,
                triggered_by=_get_actor(db, user_id),
            )
            job_ids.append(job.id)
    except ValueError as exc:
        _logger.warning("Ad-hoc scan request rejected: %s", exc)
        msg = str(exc)
        if "Too many scans" in msg:
            raise HTTPException(status_code=429, detail=msg) from None
        raise HTTPException(status_code=422, detail="Invalid scan request parameters.") from None
    except Exception as exc:
        _logger.exception("Ad-hoc scan failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while starting the scan.",
        ) from exc

    try:
        log_audit(
            db,
            request,
            user_id=user_id,
            action="scan_triggered",
            resource=",".join(f"scan_job:{job_id}" for job_id in job_ids),
            status="ok",
        )
    except Exception as audit_exc:
        _logger.warning(
            "Audit log failed for scan_triggered (jobs %s): %s",
            job_ids,
            audit_exc,
        )

    try:
        for job_id in job_ids:
            asyncio.create_task(discovery_service.run_scan_job(job_id))
    except Exception as task_exc:
        _logger.exception("Failed to schedule scan job(s) %s: %s", job_ids, task_exc)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while starting the scan.",
        ) from task_exc

    ordered_jobs = _load_jobs_in_order(db, job_ids)
    response_jobs = [ScanJobOut.model_validate(job) for job in ordered_jobs]
    if len(response_jobs) == 1:
        return response_jobs[0]
    return response_jobs


# --- Jobs ---


@router.get("/jobs", response_model=list[ScanJobOut])
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(50)).all()
    return jobs


@router.get("/jobs/{job_id}", response_model=ScanJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}", status_code=200)
async def cancel_job(
    job_id: int,
    request: Request,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    """B9: Cancel a running or queued scan job."""
    from app.core.time import utcnow_iso

    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Job is already {job.status}")
    job.status = "cancelled"
    job.completed_at = utcnow_iso()
    db.commit()
    log_audit(
        db,
        request,
        user_id=user.id,
        action="scan_cancelled",
        resource=f"scan_job:{job_id}",
        status="ok",
        severity="warn",
    )
    asyncio.create_task(
        discovery_service._emit_ws_event(
            "job_update", {"job": ScanJobOut.model_validate(job).model_dump()}
        )
    )
    return {"cancelled": True}


@router.get("/proxmox-runs", response_model=list[ProxmoxDiscoverRunOut])
def list_proxmox_runs(
    integration_id: int | None = Query(None, description="Filter by Proxmox integration ID"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """List Proxmox discovery runs (history), most recent first."""
    runs = list_proxmox_discover_runs(db, integration_id=integration_id, limit=limit)
    return [ProxmoxDiscoverRunOut.model_validate(r) for r in runs]


@router.get("/proxmox-runs/{run_id}", response_model=ProxmoxDiscoverRunOut)
def get_proxmox_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Get a single Proxmox discovery run by id."""
    run = get_proxmox_discover_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Proxmox discover run not found")
    return ProxmoxDiscoverRunOut.model_validate(run)


@router.get("/jobs/{job_id}/results")
def get_job_results(
    job_id: int,
    limit: int = 100,
    with_inference: bool = False,
    db: Session = Depends(get_db),
):
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    results = db.scalars(
        select(ScanResult)
        .where(ScanResult.scan_job_id == job_id)
        .order_by(ScanResult.created_at.desc())
        .limit(limit)
    ).all()

    if not with_inference:
        return [ScanResultOut.model_validate(r) for r in results]

    from app.schemas.discovery import InferredScanResultOut
    from app.services.inference_service import annotate_result

    # Build existing IP/MAC lookup maps (fresh, not from stale ScanJob.hosts_new)
    existing_by_ip: dict[str, int] = {
        h.ip_address: h.id
        for h in db.query(Hardware.ip_address, Hardware.id)
        .filter(Hardware.ip_address.isnot(None))
        .all()
    }
    existing_by_mac: dict[str, int] = {
        h.mac_address: h.id
        for h in db.query(Hardware.mac_address, Hardware.id)
        .filter(Hardware.mac_address.isnot(None))
        .all()
    }

    enriched = []
    for r in results:
        ann = annotate_result(r)
        hw_id = existing_by_mac.get(r.mac_address) if r.mac_address else None
        if hw_id is None:
            hw_id = existing_by_ip.get(r.ip_address) if r.ip_address else None
        out = InferredScanResultOut.model_validate(r)
        out.inferred_vendor = ann.vendor
        out.inferred_role = ann.role
        out.inferred_icon_slug = ann.vendor_icon_slug
        out.confidence = ann.confidence
        out.signals_used = ann.signals_used
        out.exists_in_hardware = hw_id is not None
        out.existing_hardware_id = hw_id
        out.is_new = hw_id is None
        enriched.append(out)
    return enriched


@router.post("/jobs/{job_id}/batch-import")
def batch_import_results(
    job_id: int,
    payload: BatchImportRequest,
    _user=require_write_auth,
    db: Session = Depends(get_db),
):
    """Batch import selected scan results as Hardware nodes. Requires write role."""
    from app.services.discovery_import_service import batch_import

    job = db.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return batch_import(db, job_id, payload, actor="api")


@router.get("/jobs/{job_id}/logs", response_model=list[ScanLogOut])
def get_job_logs(
    job_id: int, level: str | None = None, limit: int = 100, db: Session = Depends(get_db)
):
    """Get scan logs for a specific job, optionally filtered by level."""
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    query = select(ScanLog).where(ScanLog.scan_job_id == job_id)

    if level:
        query = query.where(ScanLog.level == level.upper())

    logs = db.scalars(query.order_by(ScanLog.timestamp.asc()).limit(limit)).all()

    return logs


# --- Results ---


@router.get("/results", response_model=list[ScanResultOut])
def list_results(status: str = "pending", job_id: int | None = None, db: Session = Depends(get_db)):
    q = select(ScanResult)
    if status != "all":
        q = q.where(ScanResult.merge_status == status)
    if job_id:
        q = q.where(ScanResult.scan_job_id == job_id)

    results = db.scalars(q.order_by(ScanResult.created_at.desc())).all()
    return results


@router.post("/results/{result_id}/merge")
def merge_result(
    result_id: int,
    payload: MergeRequest,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    return discovery_service.merge_scan_result(
        db,
        result_id,
        payload.action,
        payload.entity_type,
        payload.overrides,
        actor=_get_actor(db, user.id),
    )


@router.post("/results/bulk-merge")
def bulk_merge(
    payload: BulkMergeRequest,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    return discovery_service.bulk_merge_results(
        db, payload.result_ids, payload.action, actor=_get_actor(db, user.id)
    )


@router.post("/results/enhanced-bulk-merge")
def enhanced_bulk_merge(
    payload: EnhancedBulkMergeRequest,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    return discovery_service.enhanced_bulk_merge(db, payload, actor=_get_actor(db, user.id))


@router.post("/results/suggest")
def suggest_actions(
    payload: BulkSuggestRequest,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    return suggest_bulk_actions(db, payload.result_ids)


@router.get("/vendor-catalog")
def vendor_catalog():
    return get_vendor_catalog()


# ── Docker discovery endpoints ───────────────────────────────────────────────


@router.get("/docker/status")
def docker_status(db: Session = Depends(get_db)):
    """Return Docker socket connectivity status and last sync summary."""
    from app.services.docker_discovery import get_docker_status, get_last_sync_result

    settings = get_or_create_settings(db)
    socket_path = getattr(settings, "docker_socket_path", _DEFAULT_DOCKER_SOCKET)
    status = get_docker_status(socket_path)
    last_sync = get_last_sync_result()
    return {**status, "last_sync": last_sync}


@router.post("/docker/sync")
def docker_sync(
    background_tasks: BackgroundTasks,
    user: User = require_role("admin"),
    db: Session = Depends(get_db),
):
    """Trigger an immediate Docker topology sync (runs in background)."""
    from app.services.docker_discovery import sync_docker_topology

    settings = get_or_create_settings(db)
    socket_path = getattr(settings, "docker_socket_path", _DEFAULT_DOCKER_SOCKET)
    background_tasks.add_task(sync_docker_topology, socket_path=socket_path)
    return {"status": "sync_started", "socket_path": socket_path}


@router.get("/docker/networks")
def docker_networks(db: Session = Depends(get_db)):
    """List all Network rows that were discovered via Docker."""
    from sqlalchemy import select as _select

    from app.db.models import Network

    nets = db.scalars(
        _select(Network).where(Network.is_docker_network == True)  # noqa: E712
    ).all()
    return [
        {
            "id": n.id,
            "name": n.name,
            "docker_network_id": n.docker_network_id,
            "docker_driver": n.docker_driver,
            "cidr": n.cidr,
            "gateway": n.gateway,
            "created_at": n.created_at,
            "updated_at": n.updated_at,
        }
        for n in nets
    ]


# ── Phase 4: Always-On Listener ──────────────────────────────────────────────


@router.get("/listener/status")
def get_listener_status():
    """Return whether the mDNS/SSDP listener is running."""
    from app.services.listener_service import listener_service

    return {
        "running": listener_service.is_running,
        "mdns_active": listener_service.mdns_active,
        "ssdp_active": listener_service.ssdp_active,
    }


@router.get("/listener/events")
def get_listener_events(
    limit: int = 100,
    source: str | None = None,
    db: Session = Depends(get_db),
):
    """Return recent listener events (mDNS / SSDP), newest first."""
    q = db.query(ListenerEvent).order_by(ListenerEvent.seen_at.desc())
    if source:
        q = q.filter(ListenerEvent.source == source)
    events = q.limit(min(limit, 500)).all()
    return [
        {
            "id": e.id,
            "source": e.source,
            "service_type": e.service_type,
            "name": e.name,
            "ip_address": e.ip_address,
            "port": e.port,
            "properties_json": e.properties_json,
            "seen_at": e.seen_at.isoformat() if e.seen_at else None,
        }
        for e in events
    ]


# ── v0.2.0: Self-Aware Cluster Topology ─────────────────────────────────────


@router.post("/self-cluster")
def trigger_self_cluster(db: Session = Depends(get_db), user: User = require_role("admin")):
    """Detect Circuit Breaker containers and group them into a cluster node."""
    from app.services.self_discovery import autocreate_self_cluster

    return autocreate_self_cluster(db)


@router.get("/self-cluster/status")
def get_self_cluster_status(db: Session = Depends(get_db), user: User = require_role("admin")):
    """Return the current Circuit Breaker self-cluster state."""
    from app.db.models import HardwareCluster, HardwareClusterMember

    cluster = db.query(HardwareCluster).filter_by(name="Circuit Breaker").first()
    if not cluster:
        return {"cluster_id": None, "member_count": 0, "members": []}
    members = db.query(HardwareClusterMember).filter_by(cluster_id=cluster.id).all()
    return {
        "cluster_id": cluster.id,
        "member_count": len(members),
        "members": [
            {
                "id": m.id,
                "member_type": m.member_type,
                "service_id": m.service_id,
                "hardware_id": m.hardware_id,
            }
            for m in members
        ],
    }

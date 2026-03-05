import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.scheduler import _scheduler
from app.core.security import require_auth_always, require_write_auth
from app.db.models import ScanJob, ScanResult, User
from app.db.session import get_db
from app.schemas.discovery import (
    AdHocScanRequest,
    BulkMergeRequest,
    BulkSuggestRequest,
    DiscoveryProfileCreate,
    DiscoveryProfileOut,
    DiscoveryProfileUpdate,
    DiscoveryStatusOut,
    EnhancedBulkMergeRequest,
    MergeRequest,
    ScanJobOut,
    ScanResultOut,
)
from app.services import discovery_profiles_service, discovery_service
from app.services.bulk_suggest import get_vendor_catalog, suggest_bulk_actions
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["discovery"])


def _get_actor(db: Session, user_id: int) -> str:
    if user_id == 0:
        return "api-token"
    u = db.query(User).filter(User.id == user_id).first()
    return u.email if u else "unknown"


@router.get("/status", response_model=DiscoveryStatusOut)
def get_discovery_status(db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    
    pending_count = db.scalar(select(func.count()).where(ScanResult.merge_status == "pending")) or 0
    active_jobs = db.scalars(select(ScanJob).where(ScanJob.status.in_(["queued", "running"]))).all()
    
    last_scan = db.scalar(select(func.max(ScanJob.started_at)))
    
    # Simple check for next scheduled run time
    next_scheduled = None
    if _scheduler.running:
        job_times = []
        for j in _scheduler.get_jobs():
            if j.id.startswith("discovery_profile_") and j.next_run_time:
                job_times.append(j.next_run_time)
        if job_times:
            next_scheduled = min(job_times).isoformat()
            
    return DiscoveryStatusOut(
        discovery_enabled=settings.discovery_enabled,
        scan_ack_accepted=settings.scan_ack_accepted,
        pending_results=pending_count,
        active_jobs=[ScanJobOut.model_validate(j) for j in active_jobs],
        last_scan=last_scan,
        next_scheduled=next_scheduled
    )


# --- Profiles ---

@router.get("/profiles", response_model=list[DiscoveryProfileOut])
def get_profiles(db: Session = Depends(get_db)):
    return discovery_profiles_service.get_profiles(db)

@router.post("/profiles", response_model=DiscoveryProfileOut)
def create_profile(
    payload: DiscoveryProfileCreate,
    req: Request,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db)
):
    actor = _get_actor(db, user_id)
    return discovery_profiles_service.create_profile(db, payload, actor)

@router.patch("/profiles/{profile_id}", response_model=DiscoveryProfileOut)
def update_profile(
    profile_id: int,
    payload: DiscoveryProfileUpdate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db)
):
    actor = _get_actor(db, user_id)
    return discovery_profiles_service.update_profile(db, profile_id, payload, actor)

@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db)
):
    actor = _get_actor(db, user_id)
    discovery_profiles_service.delete_profile(db, profile_id, actor)
    return None

@router.post("/profiles/{profile_id}/run", response_model=ScanJobOut)
@limiter.limit("1/minute")
async def run_profile_scan(
    request: Request,
    profile_id: int,
    bg_tasks: BackgroundTasks,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db)
):
    profile = discovery_profiles_service.get_profile(db, profile_id)
    if not profile.enabled:
        raise HTTPException(status_code=400, detail="Profile is disabled")

    import json
    job = discovery_service.create_scan_job(
        db,
        target_cidr=profile.cidr,
        scan_types=json.loads(profile.scan_types),
        profile_id=profile.id,
        triggered_by=_get_actor(db, user_id)
    )

    # B2: async def endpoint runs on the event loop — asyncio.create_task works here
    asyncio.create_task(discovery_service.run_scan_job(job.id))
    return job


# --- Ad-Hoc ---

@router.post("/scan", response_model=ScanJobOut)
@limiter.limit("1/minute")
async def run_adhoc_scan(
    request: Request,
    payload: AdHocScanRequest,
    bg_tasks: BackgroundTasks,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db)
):
    try:
        job = discovery_service.create_scan_job(
            db,
            target_cidr=payload.cidr,
            scan_types=payload.scan_types,
            nmap_arguments=payload.nmap_arguments,  # B12: thread through
            label=payload.label,
            triggered_by=_get_actor(db, user_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # B2: async def — asyncio.create_task schedules on the running event loop
    asyncio.create_task(discovery_service.run_scan_job(job.id))
    return job


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
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db)
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
    asyncio.create_task(discovery_service._emit_ws_event(
        "job_update", {"job": ScanJobOut.model_validate(job).model_dump()}
    ))
    return {"cancelled": True}

@router.get("/jobs/{job_id}/results", response_model=list[ScanResultOut])
def get_job_results(job_id: int, limit: int = 100, db: Session = Depends(get_db)):
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    results = db.scalars(
        select(ScanResult).where(ScanResult.scan_job_id == job_id)
        .order_by(ScanResult.created_at.desc()).limit(limit)
    ).all()
    return results


# --- Results ---

@router.get("/results", response_model=list[ScanResultOut])
def list_results(status: str = "pending", job_id: int = None, db: Session = Depends(get_db)):
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
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db)
):
    return discovery_service.merge_scan_result(
        db, result_id, payload.action, payload.entity_type, payload.overrides, actor=_get_actor(db, user_id)
    )

@router.post("/results/bulk-merge")
def bulk_merge(
    payload: BulkMergeRequest,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db)
):
    return discovery_service.bulk_merge_results(db, payload.result_ids, payload.action, actor=_get_actor(db, user_id))


@router.post("/results/enhanced-bulk-merge")
def enhanced_bulk_merge(
    payload: EnhancedBulkMergeRequest,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db)
):
    return discovery_service.enhanced_bulk_merge(db, payload, actor=_get_actor(db, user_id))


@router.post("/results/suggest")
def suggest_actions(
    payload: BulkSuggestRequest,
    db: Session = Depends(get_db),
):
    return suggest_bulk_actions(db, payload.result_ids)


@router.get("/vendor-catalog")
def vendor_catalog():
    return get_vendor_catalog()

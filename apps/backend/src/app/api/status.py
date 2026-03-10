"""Status page API: pages, groups, history, dashboard, refresh."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.status import (
    AvailableEntitiesResponse,
    BulkGroupCreate,
    BulkGroupResponse,
    DashboardGlobalSummary,
    DashboardGroupItem,
    DashboardResponse,
    DashboardV2Response,
    StatusEventRead,
    StatusGroupCreate,
    StatusGroupRead,
    StatusGroupUpdate,
    StatusHistoryRead,
    StatusPageCreate,
    StatusPageRead,
    StatusPageUpdate,
)
from app.services import status_page_service as svc

router = APIRouter()

_MSG_PAGE_NOT_FOUND = "Status page not found"
_MSG_GROUP_NOT_FOUND = "Status group not found"


def _page_read(p):
    return StatusPageRead(
        id=p.id,
        slug=p.slug,
        name=p.name,
        config=json.loads(p.config) if p.config else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("/pages", response_model=list[StatusPageRead])
def list_pages(db: Session = Depends(get_db)):
    """List all status pages; ensures default page exists."""
    svc.get_or_create_default_page(db)
    pages = svc.list_status_pages(db)
    return [_page_read(p) for p in pages]


@router.get("/pages/{page_id}", response_model=StatusPageRead)
def get_page(page_id: int, db: Session = Depends(get_db)):
    page = svc.get_status_page(db, page_id)
    if not page:
        raise HTTPException(status_code=404, detail=_MSG_PAGE_NOT_FOUND)
    return _page_read(page)


@router.post("/pages", response_model=StatusPageRead)
def create_page(
    data: StatusPageCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    page = svc.create_status_page(db, data)
    return _page_read(page)


@router.patch("/pages/{page_id}", response_model=StatusPageRead)
def update_page(
    page_id: int,
    data: StatusPageUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    page = svc.update_status_page(db, page_id, data)
    if not page:
        raise HTTPException(status_code=404, detail=_MSG_PAGE_NOT_FOUND)
    return _page_read(page)


@router.delete("/pages/{page_id}", status_code=204)
def delete_page(
    page_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    if not svc.delete_status_page(db, page_id):
        raise HTTPException(status_code=404, detail=_MSG_PAGE_NOT_FOUND)


@router.get("/pages/{page_id}/groups", response_model=list[StatusGroupRead])
def list_groups(page_id: int, db: Session = Depends(get_db)):
    if not svc.get_status_page(db, page_id):
        raise HTTPException(status_code=404, detail=_MSG_PAGE_NOT_FOUND)
    groups = svc.list_groups_for_page(db, page_id)
    return [StatusGroupRead.model_validate(g) for g in groups]


@router.post("/groups", response_model=StatusGroupRead)
def create_group(
    data: StatusGroupCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    if not svc.get_status_page(db, data.status_page_id):
        raise HTTPException(status_code=404, detail=_MSG_PAGE_NOT_FOUND)
    group = svc.create_status_group(db, data)
    return StatusGroupRead.model_validate(group)


@router.post("/groups/bulk", response_model=BulkGroupResponse)
def bulk_create_group(
    data: BulkGroupCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    if not svc.get_status_page(db, data.page_id):
        raise HTTPException(status_code=404, detail=_MSG_PAGE_NOT_FOUND)
    group = svc.bulk_create_group(
        db,
        name=data.name,
        page_id=data.page_id,
        entity_ids=data.entity_ids,
        entity_type=data.entity_type,
    )
    return {"group_id": group.id, "added": len(data.entity_ids)}


@router.patch("/groups/{group_id}", response_model=StatusGroupRead)
def update_group(
    group_id: int,
    data: StatusGroupUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    add_node = getattr(data, "add_node", None)
    group = svc.update_status_group(db, group_id, data, add_node=add_node)
    if not group:
        raise HTTPException(status_code=404, detail=_MSG_GROUP_NOT_FOUND)
    return StatusGroupRead.model_validate(group)


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    if not svc.delete_status_group(db, group_id):
        raise HTTPException(status_code=404, detail=_MSG_GROUP_NOT_FOUND)


@router.get("/history", response_model=list[StatusHistoryRead])
def list_history(
    group_id: int | None = Query(None),
    range_param: str = Query("7d", alias="range"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = svc.list_history(
        db, group_id=group_id, range_param=range_param, limit=limit, offset=offset
    )
    return [StatusHistoryRead.model_validate(r) for r in rows]


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard_legacy(db: Session = Depends(get_db)):
    """Legacy dashboard response (pages + groups + history_sample) for Settings and older clients."""
    pages, snapshots = svc.get_dashboard_snapshots(db)
    page_reads = [_page_read(p) for p in pages]
    history_by_group = svc.get_latest_history_per_group(db, limit_per_group=100)
    history_sample = {}
    for gid, rows in history_by_group.items():
        history_sample[gid] = [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "overall_status": r.overall_status,
                "uptime_pct": r.uptime_pct,
                "avg_ping": r.avg_ping,
            }
            for r in rows
        ]
    return DashboardResponse(
        pages=page_reads,
        groups=snapshots,
        history_sample=history_sample,
    )


@router.get("/dashboard/v2", response_model=DashboardV2Response)
async def get_dashboard_v2(
    group_id: int | None = Query(None, description="Filter to one group"),
    range_param: str = Query("7d", alias="range", description="1h | 24h | 7d | 30d"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Dashboard v2: groups with entity count, metrics, history series, and global summary. Cached 300s."""
    from app.core.nats_client import nats_client

    cache_key = f"dashboard_v2:{group_id or 'all'}:{range_param}:{limit}"

    if nats_client.is_connected:
        try:
            cached_data = await nats_client.kv_get("dashboard_cache", cache_key)
            if cached_data:
                payload = json.loads(cached_data)
                groups_models = [DashboardGroupItem.model_validate(g) for g in payload["groups"]]
                global_model = DashboardGlobalSummary.model_validate(payload["global"])
                return DashboardV2Response(groups=groups_models, global_=global_model)
        except Exception:
            pass  # Fallback to DB on cache miss/error

    groups_list, global_summary = svc.get_dashboard_payload(
        db, group_id=group_id, range_param=range_param, limit=limit
    )

    groups_models = [DashboardGroupItem.model_validate(g) for g in groups_list]
    global_model = DashboardGlobalSummary.model_validate(global_summary)

    if nats_client.is_connected:
        try:
            cache_payload = {
                "groups": [g.model_dump() for g in groups_models],
                "global": global_model.model_dump(),
            }
            # Cache for 300s. Since NATS KV put doesn't take TTL per-key directly,
            # we rely on bucket TTL or just let clients do cache busts. For a simple implementation,
            # this sets the value directly.
            await nats_client.kv_put("dashboard_cache", cache_key, json.dumps(cache_payload))
        except Exception:
            pass

    return DashboardV2Response(groups=groups_models, global_=global_model)


@router.get("/groups/{group_id}/events", response_model=list[StatusEventRead])
def list_group_events(
    group_id: int,
    since: str = Query("7d", description="1h | 24h | 7d | 30d"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List events for a status group within the since window."""
    if not svc.get_status_group(db, group_id):
        raise HTTPException(status_code=404, detail=_MSG_GROUP_NOT_FOUND)
    events = svc.list_events_for_group(db, group_id=group_id, since_param=since, limit=limit)
    return [StatusEventRead.model_validate(e) for e in events]


@router.get("/available-entities", response_model=AvailableEntitiesResponse)
def get_available_entities(
    q: str | None = Query(None),
    role: str | None = Query(None),
    status: str | None = Query(None),
    entity_type: str | None = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List all hardware and services not currently assigned to any status group."""
    entities, total = svc.list_available_entities(
        db,
        q=q,
        role=role,
        status=status,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )
    return {"entities": entities, "total": total}


@router.post("/refresh")
def refresh_status(_=Depends(require_write_auth)):
    """Trigger one-off status poll for all groups."""
    from app.workers.status_worker import run_status_poll_job

    run_status_poll_job()
    return {"status": "ok", "message": "Refresh started"}

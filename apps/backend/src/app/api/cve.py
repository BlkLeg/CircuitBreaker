"""CVE API — search, entity lookup, manual sync trigger, and status."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.security import require_write_auth
from app.services import cve_service

router = APIRouter(tags=["cve"])


@router.get("/search")
def search_cves(
    q: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    results, total = cve_service.search_cves(
        query=q,
        vendor=vendor,
        product=product,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return {"items": results, "total": total}


@router.get("/entity/{entity_type}/{entity_id}")
def cves_for_entity(entity_type: str, entity_id: int) -> dict:
    items = cve_service.cves_for_entity(entity_type, entity_id)
    return {"items": items, "total": len(items)}


@router.post("/sync", dependencies=[Depends(require_write_auth)])
def trigger_sync(background_tasks: BackgroundTasks) -> dict:
    """Trigger an immediate NVD CVE feed sync in the background."""
    background_tasks.add_task(cve_service.sync_nvd_feed)
    return {"status": "sync_started"}


@router.get("/status")
def cve_status() -> dict:
    return cve_service.get_status()

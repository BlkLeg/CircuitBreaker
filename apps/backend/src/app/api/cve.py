"""CVE API — search, entity lookup, manual sync trigger, and status."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.security import require_write_auth
from app.schemas.cve import AssessmentIdentity, AssessmentResult, IdentityPatch
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


@router.get("/entity/{entity_type}/{entity_id}", response_model=AssessmentResult)
def cves_for_entity(entity_type: str, entity_id: int) -> AssessmentResult:
    if entity_type not in {"hardware", "compute_unit", "service"}:
        return AssessmentResult(
            state="unassessed",
            reason_code="identity_missing",
            identity=None,
            identity_revision=0,
            feed_generation=None,
            feed_age_seconds=None,
            assessed_at=datetime.now(UTC),
            findings=[],
            total=0,
            completeness="none",
            limitations=["This entity type does not support vulnerability assessment."],
        )
    return cve_service.assessment_for_entity(entity_type, entity_id)


@router.put(
    "/entity/{entity_type}/{entity_id}/identity",
    response_model=AssessmentIdentity,
)
def update_entity_identity(
    entity_type: str,
    entity_id: int,
    payload: IdentityPatch,
    user_id: Annotated[int | None, Depends(require_write_auth)] = None,
) -> AssessmentIdentity:
    actor = "legacy_admin" if user_id == 0 else (str(user_id) if user_id else None)
    return cve_service.set_entity_identity(entity_type, entity_id, payload, actor=actor)


@router.post("/sync", dependencies=[Depends(require_write_auth)])
def trigger_sync(background_tasks: BackgroundTasks) -> dict:
    """Trigger an immediate NVD CVE feed sync in the background."""
    background_tasks.add_task(cve_service.sync_nvd_feed)
    return {"status": "sync_started"}


@router.get("/status")
def cve_status() -> dict:
    return cve_service.get_status()

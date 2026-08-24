"""Intelligence API endpoints: blast-radius, capacity forecasts, resource efficiency."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.db.models import CapacityForecast, ResourceEfficiencyRecommendation
from app.db.session import get_db
from app.services.intelligence.dependency_graph import AssetRef, calculate_blast_radius

router = APIRouter()

_VALID_TYPES = frozenset({"hardware", "compute_unit", "service", "storage"})


class AssetRefOut(BaseModel):
    asset_type: str
    asset_id: int
    name: str
    status: str | None


class BlastRadiusOut(BaseModel):
    root_asset: AssetRefOut
    impacted_hardware: list[AssetRefOut]
    impacted_compute_units: list[AssetRefOut]
    impacted_services: list[AssetRefOut]
    impacted_storage: list[AssetRefOut]
    total_impact_count: int
    summary: str


class CapacityForecastOut(BaseModel):
    id: int
    hardware_id: int
    hardware_name: str | None = None
    metric: str
    slope_per_day: float
    current_value: float
    projected_full_at: datetime | None
    warning_threshold_days: int
    evaluated_at: datetime

    model_config = {"from_attributes": True}


class ResourceEfficiencyOut(BaseModel):
    id: int
    asset_type: str
    asset_id: int
    asset_name: str | None = None
    classification: str
    cpu_avg_pct: float | None
    cpu_peak_pct: float | None
    mem_avg_pct: float | None
    recommendation: str
    evaluated_at: datetime

    model_config = {"from_attributes": True}


def _ref_out(r: AssetRef) -> AssetRefOut:
    return AssetRefOut(
        asset_type=r.asset_type,
        asset_id=r.asset_id,
        name=r.name,
        status=r.status,
    )


@router.get("/blast-radius/{asset_type}/{asset_id}", response_model=BlastRadiusOut)
def get_blast_radius(
    asset_type: str,
    asset_id: int,
    db: Session = Depends(get_db),
) -> BlastRadiusOut:
    """Compute downstream impact of an asset going offline."""
    if asset_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid asset_type: {asset_type!r}")
    result = calculate_blast_radius(db, asset_type, asset_id)
    return BlastRadiusOut(
        root_asset=_ref_out(result.root_asset),
        impacted_hardware=[_ref_out(r) for r in result.impacted_hardware],
        impacted_compute_units=[_ref_out(r) for r in result.impacted_compute_units],
        impacted_services=[_ref_out(r) for r in result.impacted_services],
        impacted_storage=[_ref_out(r) for r in result.impacted_storage],
        total_impact_count=result.total_impact_count,
        summary=result.summary,
    )


@router.get("/capacity-forecasts", response_model=list[CapacityForecastOut])
def list_capacity_forecasts(db: Session = Depends(get_db)) -> list[CapacityForecastOut]:
    """Return all capacity forecasts ordered by projected saturation date.

    The hardware name is joined in rather than left to the caller.
    """
    rows = (
        db.query(CapacityForecast)
        .options(joinedload(CapacityForecast.hardware))
        .order_by(CapacityForecast.projected_full_at.asc().nulls_last())
        .all()
    )
    out: list[CapacityForecastOut] = []
    for row in rows:
        item = CapacityForecastOut.model_validate(row)
        item.hardware_name = getattr(row.hardware, "name", None)
        out.append(item)
    return out


def _resolve_asset_names(
    db: Session, rows: list[ResourceEfficiencyRecommendation]
) -> dict[tuple[str, int], str]:
    """id -> name for every asset referenced by `rows`, in one query per
    asset TYPE present (at most four), never one per row.
    """
    from app.services.intelligence.dependency_graph import _MODEL_MAP

    by_type: dict[str, set[int]] = {}
    for row in rows:
        by_type.setdefault(row.asset_type, set()).add(row.asset_id)

    names: dict[tuple[str, int], str] = {}
    for asset_type, ids in by_type.items():
        model = _MODEL_MAP.get(asset_type)
        if model is None:
            continue
        for obj_id, name in db.query(model.id, model.name).filter(model.id.in_(ids)).all():
            names[(asset_type, obj_id)] = name
    return names


@router.get("/resource-efficiency", response_model=list[ResourceEfficiencyOut])
def list_resource_efficiency(
    db: Session = Depends(get_db),
) -> list[ResourceEfficiencyOut]:
    """Return right-sizing recommendations for all assessed assets."""
    rows = (
        db.query(ResourceEfficiencyRecommendation)
        .order_by(ResourceEfficiencyRecommendation.evaluated_at.desc())
        .all()
    )
    names = _resolve_asset_names(db, rows)
    out: list[ResourceEfficiencyOut] = []
    for row in rows:
        item = ResourceEfficiencyOut.model_validate(row)
        item.asset_name = names.get((row.asset_type, row.asset_id))
        out.append(item)
    return out

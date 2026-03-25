from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.models import MapPinnedEntity, Topology, TopologyNode
from app.db.session import get_db
from app.schemas.map import EntityAssign, EntityPin, MapCreate, MapOut, MapUpdate

router = APIRouter(tags=["maps"])

_MAX_MAPS = 10


def _get_map_or_404(db: Session, map_id: int) -> Topology:
    topo = db.get(Topology, map_id)
    if not topo:
        raise HTTPException(status_code=404, detail=f"Map {map_id} not found")
    return topo


def _entity_count(db: Session, topology_id: int) -> int:
    return db.scalar(select(func.count()).where(TopologyNode.topology_id == topology_id)) or 0


@router.get("", response_model=list[MapOut])
def list_maps(db: Session = Depends(get_db)) -> Any:
    topos = db.execute(select(Topology).order_by(Topology.sort_order, Topology.id)).scalars().all()
    result = []
    for t in topos:
        out = MapOut.model_validate(t)
        out.entity_count = _entity_count(db, t.id)
        result.append(out)
    return result


@router.post("", response_model=MapOut, status_code=201)
def create_map(
    payload: MapCreate,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    count = db.scalar(select(func.count()).select_from(Topology)) or 0
    if count >= _MAX_MAPS:
        raise HTTPException(
            status_code=409,
            detail=f"Map limit reached ({_MAX_MAPS}). Delete a map before creating a new one.",
        )
    max_order = db.scalar(select(func.max(Topology.sort_order))) or 0
    topo = Topology(name=payload.name, is_default=False, sort_order=max_order + 1)
    db.add(topo)
    db.commit()
    db.refresh(topo)
    out = MapOut.model_validate(topo)
    out.entity_count = 0
    return out


# --- Global pin (must be declared before /{map_id} to avoid route shadowing) ---


@router.post("/pin", status_code=201)
def pin_entity(
    payload: EntityPin,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> dict:
    exists = db.get(MapPinnedEntity, (payload.entity_type, payload.entity_id))
    if not exists:
        db.add(MapPinnedEntity(entity_type=payload.entity_type, entity_id=payload.entity_id))
        db.commit()
    return {"ok": True}


@router.delete("/pin/{entity_type}/{entity_id}", status_code=204)
def unpin_entity(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> None:
    pin = db.get(MapPinnedEntity, (entity_type, entity_id))
    if pin:
        db.delete(pin)
        db.commit()


@router.patch("/{map_id}", response_model=MapOut)
def update_map(
    map_id: int,
    payload: MapUpdate,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    topo = _get_map_or_404(db, map_id)
    if payload.name is not None:
        topo.name = payload.name
    if payload.sort_order is not None:
        topo.sort_order = payload.sort_order
    db.commit()
    db.refresh(topo)
    out = MapOut.model_validate(topo)
    out.entity_count = _entity_count(db, topo.id)
    return out


@router.delete("/{map_id}", status_code=204)
def delete_map(
    map_id: int,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> None:
    topo = _get_map_or_404(db, map_id)
    total = db.scalar(select(func.count()).select_from(Topology)) or 0
    if total <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the last map.")

    # Re-assign exclusive nodes to the default (or lowest-order) map
    default = db.scalar(select(Topology).where(Topology.is_default == True))  # noqa: E712
    if not default or default.id == map_id:
        # Fallback: pick the lowest sort_order map that isn't the one being deleted
        default = db.scalar(
            select(Topology).where(Topology.id != map_id).order_by(Topology.sort_order, Topology.id)
        )
    if default:
        exclusive_nodes = (
            db.execute(select(TopologyNode).where(TopologyNode.topology_id == map_id))
            .scalars()
            .all()
        )
        pinned_set = {
            (r.entity_type, r.entity_id)
            for r in db.execute(
                select(MapPinnedEntity.entity_type, MapPinnedEntity.entity_id)
            ).all()
        }
        for node in exclusive_nodes:
            if (node.entity_type, node.entity_id) in pinned_set:
                continue
            exists = db.scalar(
                select(TopologyNode).where(
                    TopologyNode.topology_id == default.id,
                    TopologyNode.entity_type == node.entity_type,
                    TopologyNode.entity_id == node.entity_id,
                )
            )
            if not exists:
                db.add(
                    TopologyNode(
                        topology_id=default.id,
                        entity_type=node.entity_type,
                        entity_id=node.entity_id,
                    )
                )

    db.delete(topo)
    db.commit()


# --- Entity assignment ---


@router.post("/{map_id}/entities", status_code=201)
def assign_entity(
    map_id: int,
    payload: EntityAssign,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> dict:
    _get_map_or_404(db, map_id)
    exists = db.scalar(
        select(TopologyNode).where(
            TopologyNode.topology_id == map_id,
            TopologyNode.entity_type == payload.entity_type,
            TopologyNode.entity_id == payload.entity_id,
        )
    )
    if not exists:
        db.add(
            TopologyNode(
                topology_id=map_id,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
            )
        )
        db.commit()
    return {"ok": True}


@router.delete("/{map_id}/entities/{entity_type}/{entity_id}", status_code=204)
def remove_entity(
    map_id: int,
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> None:
    node = db.scalar(
        select(TopologyNode).where(
            TopologyNode.topology_id == map_id,
            TopologyNode.entity_type == entity_type,
            TopologyNode.entity_id == entity_id,
        )
    )
    if node:
        db.delete(node)
        db.commit()

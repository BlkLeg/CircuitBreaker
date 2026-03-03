from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.hardware import Hardware, HardwareCreate, HardwareUpdate, PortEntry
from app.services import hardware_service, clusters_service
from app.services.compute_units_service import get_compute_unit

router = APIRouter(tags=["hardware"])


@router.get("", response_model=list[Hardware])
def list_hardware(
    tag: str | None = Query(None),
    role: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return hardware_service.list_hardware(db, tag=tag, role=role, q=q)


@router.post("", response_model=Hardware, status_code=201)
def create_hardware(payload: HardwareCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return hardware_service.create_hardware(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.get("/orphans")
def get_orphans(db: Session = Depends(get_db)):
    """CB-PATTERN-003: Hardware with no compute_units, services, or storage."""
    return hardware_service.find_orphans(db)


@router.get("/groups")
def get_groups(db: Session = Depends(get_db)):
    """CB-PATTERN-004: Hardware grouped by vendor+model with counts."""
    return hardware_service.list_hardware_groups(db)


@router.get("/{hardware_id}", response_model=Hardware)
def get_hardware(hardware_id: int, db: Session = Depends(get_db)):
    try:
        return hardware_service.get_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{hardware_id}", response_model=Hardware)
def replace_hardware(hardware_id: int, payload: HardwareCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    update = HardwareUpdate(**payload.model_dump())
    try:
        return hardware_service.update_hardware(db, hardware_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.patch("/{hardware_id}", response_model=Hardware)
def patch_hardware(hardware_id: int, payload: HardwareUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return hardware_service.update_hardware(db, hardware_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{hardware_id}", status_code=204)
def delete_hardware(hardware_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        hardware_service.delete_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Cannot delete: other records still reference this hardware.")


@router.get("/{hardware_id}/network-memberships")
def get_network_memberships(hardware_id: int, db: Session = Depends(get_db)):
    """Return all networks this hardware node is directly a member of."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return hardware_service.list_network_memberships(db, hardware_id)


@router.get("/{hardware_id}/clusters")
def get_clusters_for_hardware(hardware_id: int, db: Session = Depends(get_db)):
    """Return all hardware clusters this hardware belongs to."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return clusters_service.list_for_hardware(db, hardware_id)


@router.get("/{hardware_id}/ports")
def get_hardware_ports(hardware_id: int, db: Session = Depends(get_db)) -> list[dict]:
    try:
        hw = hardware_service.get_hardware(db, hardware_id)
        return hw.get("port_map", [])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{hardware_id}/ports")
def update_hardware_ports(
    hardware_id: int,
    payload: list[PortEntry],  # Expects a list of PortEntry objects
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
) -> list[dict]:
    # Validate uniqueness of port_id within the payload
    port_ids = [p.port_id for p in payload if p.port_id is not None]
    if len(port_ids) != len(set(port_ids)):
        raise HTTPException(status_code=422, detail="Port IDs must be unique within the port map.")

    # Ensure connected_hardware_id / connected_compute_id actually exist if set
    for p in payload:
        if p.connected_hardware_id:
            try:
                hardware_service.get_hardware(db, p.connected_hardware_id)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Connected hardware {p.connected_hardware_id} not found.")
        if p.connected_compute_id:
            from app.services.compute_units_service import get_compute_unit # avoid circular import
            try:
                get_compute_unit(db, p.connected_compute_id)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Connected compute unit {p.connected_compute_id} not found.")

    # Update the hardware with the new port map. The hardware_service.update_hardware
    # function will handle the serialization to JSON and the graph edge syncing.
    try:
        updated_hw = hardware_service.update_hardware(
            db, hardware_id, HardwareUpdate(port_map=payload))
        return updated_hw.get("port_map", [])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")

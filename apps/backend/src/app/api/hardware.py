from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.hardware import Hardware, HardwareCreate, HardwareUpdate, PortEntry
from app.services import clusters_service, hardware_service

router = APIRouter(tags=["hardware"])

DUPLICATE_IDENTIFIER_ERROR = "A record with this identifier already exists."


@router.get("", response_model=list[Hardware])
def list_hardware(
    db: Annotated[Session, Depends(get_db)],
    tag: Annotated[str | None, Query()] = None,
    role: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
):
    return hardware_service.list_hardware(db, tag=tag, role=role, q=q)


@router.post(
    "",
    response_model=Hardware,
    status_code=201,
    responses={409: {"description": "A record with this identifier already exists."}},
)
def create_hardware(
    payload: HardwareCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
):
    try:
        return hardware_service.create_hardware(db, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


@router.get("/orphans")
def get_orphans(db: Annotated[Session, Depends(get_db)]):
    """CB-PATTERN-003: Hardware with no compute_units, services, or storage."""
    return hardware_service.find_orphans(db)


@router.get("/groups")
def get_groups(db: Annotated[Session, Depends(get_db)]):
    """CB-PATTERN-004: Hardware grouped by vendor+model with counts."""
    return hardware_service.list_hardware_groups(db)


@router.get(
    "/{hardware_id}",
    response_model=Hardware,
    responses={404: {"description": "Hardware not found."}},
)
def get_hardware(hardware_id: int, db: Annotated[Session, Depends(get_db)]):
    try:
        return hardware_service.get_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{hardware_id}", response_model=Hardware)
def replace_hardware(
    hardware_id: int,
    payload: HardwareCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
):
    update = HardwareUpdate(**payload.model_dump())
    try:
        return hardware_service.update_hardware(db, hardware_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


@router.patch("/{hardware_id}", response_model=Hardware)
def patch_hardware(
    hardware_id: int,
    payload: HardwareUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
):
    try:
        return hardware_service.update_hardware(db, hardware_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


@router.delete("/{hardware_id}", status_code=204)
def delete_hardware(
    hardware_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
):
    try:
        hardware_service.delete_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Cannot delete: other records still reference this hardware."
        ) from exc


@router.get("/{hardware_id}/network-memberships")
def get_network_memberships(hardware_id: int, db: Annotated[Session, Depends(get_db)]):
    """Return all networks this hardware node is directly a member of."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return hardware_service.list_network_memberships(db, hardware_id)


@router.get("/{hardware_id}/clusters")
def get_clusters_for_hardware(hardware_id: int, db: Annotated[Session, Depends(get_db)]):
    """Return all hardware clusters this hardware belongs to."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return clusters_service.list_for_hardware(db, hardware_id)


@router.get("/{hardware_id}/ports")
def get_hardware_ports(hardware_id: int, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    try:
        hw = hardware_service.get_hardware(db, hardware_id)
        return hw.get("port_map", [])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{hardware_id}/ports")
def update_hardware_ports(
    hardware_id: int,
    payload: list[PortEntry],  # Expects a list of PortEntry objects
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
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
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Connected hardware {p.connected_hardware_id} not found.",
                ) from exc
        if p.connected_compute_id:
            from app.services.compute_units_service import get_compute_unit  # avoid circular import

            try:
                get_compute_unit(db, p.connected_compute_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Connected compute unit {p.connected_compute_id} not found.",
                ) from exc

    # Update the hardware with the new port map. The hardware_service.update_hardware
    # function will handle the serialization to JSON and the graph edge syncing.
    try:
        updated_hw = hardware_service.update_hardware(
            db, hardware_id, HardwareUpdate(port_map=payload)
        )
        return updated_hw.get("port_map", [])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


# ── Hardware-to-Hardware connections ─────────────────────────────────────────


class HardwareConnectionCreate(BaseModel):
    target_hardware_id: int


@router.post("/{hardware_id}/connections", status_code=201)
async def create_hardware_connection(
    hardware_id: int,
    payload: HardwareConnectionCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
):
    """Create a direct physical connection between two hardware nodes."""
    try:
        conn = hardware_service.add_hardware_connection(db, hardware_id, payload.target_hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A connection between these hardware nodes already exists."
        ) from exc

    from app.core.nats_client import nats_client
    from app.core.subjects import TOPOLOGY_CABLE_ADDED, topology_cable_payload

    await nats_client.publish(
        TOPOLOGY_CABLE_ADDED,
        topology_cable_payload(
            f"hw-{hardware_id}",
            f"hw-{payload.target_hardware_id}",
            connection_type=conn.get("connection_type", "ethernet")
            if isinstance(conn, dict)
            else "ethernet",
        ),
    )
    return conn


# ── Standalone hardware-connection delete (by relation ID) ───────────────────

hw_conn_router = APIRouter(tags=["hardware"])


@hw_conn_router.delete("/hardware-connections/{connection_id}", status_code=204)
async def delete_hardware_connection(
    connection_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
):
    """Delete a hardware-to-hardware connection by its ID."""
    from app.core.nats_client import nats_client
    from app.core.subjects import TOPOLOGY_CABLE_REMOVED

    try:
        removed = hardware_service.remove_hardware_connection(db, connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await nats_client.publish(
        TOPOLOGY_CABLE_REMOVED,
        {
            "source_id": f"hw-{removed['source_hardware_id']}",
            "target_id": f"hw-{removed['target_hardware_id']}",
            "connection_id": connection_id,
        },
    )

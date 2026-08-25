import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rbac import require_scope
from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.hardware import Hardware, HardwareCreate, HardwareUpdate
from app.services import clusters_service, hardware_service

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["hardware"], dependencies=[require_scope("read", "*")])

DUPLICATE_IDENTIFIER_ERROR = "A record with this identifier already exists."


@router.get("", response_model=list[Hardware])
def list_hardware(
    db: Annotated[Session, Depends(get_db)],
    tag: Annotated[str | None, Query()] = None,
    role: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> list[Any]:
    return hardware_service.list_hardware(db, tag=tag, role=role, q=q)


@router.post(
    "",
    response_model=Hardware,
    status_code=201,
    responses={409: {"description": "A record with this identifier already exists."}},
)
def create_hardware(
    payload: HardwareCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[int | None, Depends(require_write_auth)] = None,
) -> Any:
    try:
        result = hardware_service.create_hardware(db, payload)
        log_audit(
            db,
            request,
            user_id=user_id,
            action="hardware_created",
            resource=f"hardware:{result['id']}",
            status="ok",
        )
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


@router.get(
    "/{hardware_id}",
    response_model=Hardware,
    responses={404: {"description": "Hardware not found."}},
)
def get_hardware(hardware_id: int, db: Annotated[Session, Depends(get_db)]) -> Any:
    try:
        return hardware_service.get_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{hardware_id}", response_model=Hardware)
def replace_hardware(
    hardware_id: int,
    payload: HardwareCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[int | None, Depends(require_write_auth)] = None,
) -> Any:
    update = HardwareUpdate(**payload.model_dump())
    try:
        result = hardware_service.update_hardware(db, hardware_id, update)
        log_audit(
            db,
            request,
            user_id=user_id,
            action="hardware_updated",
            resource=f"hardware:{hardware_id}",
            status="ok",
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


@router.patch("/{hardware_id}", response_model=Hardware)
def patch_hardware(
    hardware_id: int,
    payload: HardwareUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[int | None, Depends(require_write_auth)] = None,
) -> Any:
    try:
        result = hardware_service.update_hardware(db, hardware_id, payload)
        log_audit(
            db,
            request,
            user_id=user_id,
            action="hardware_updated",
            resource=f"hardware:{hardware_id}",
            status="ok",
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_IDENTIFIER_ERROR) from exc


@router.delete("/{hardware_id}", status_code=204)
def delete_hardware(
    hardware_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[int | None, Depends(require_write_auth)] = None,
) -> None:
    try:
        hardware_service.delete_hardware(db, hardware_id)
        log_audit(
            db,
            request,
            user_id=user_id,
            action="hardware_deleted",
            resource=f"hardware:{hardware_id}",
            status="ok",
            severity="warn",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Cannot delete: other records still reference this hardware."
        ) from exc


@router.get("/{hardware_id}/network-memberships")
def get_network_memberships(hardware_id: int, db: Annotated[Session, Depends(get_db)]) -> list[Any]:
    """Return all networks this hardware node is directly a member of."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return hardware_service.list_network_memberships(db, hardware_id)


@router.get("/{hardware_id}/clusters")
def get_clusters_for_hardware(
    hardware_id: int, db: Annotated[Session, Depends(get_db)]
) -> list[Any]:
    """Return all hardware clusters this hardware belongs to."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return clusters_service.list_for_hardware(db, hardware_id)


# ── Hardware-to-Hardware connections ─────────────────────────────────────────


class HardwareConnectionCreate(BaseModel):
    target_hardware_id: int
    connection_type: str | None = None


@router.post("/{hardware_id}/connections", status_code=201)
async def create_hardware_connection(
    hardware_id: int,
    payload: HardwareConnectionCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
) -> Any:
    """Create a direct physical connection between two hardware nodes."""
    try:
        conn = hardware_service.add_hardware_connection(
            db, hardware_id, payload.target_hardware_id, payload.connection_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A connection between these hardware nodes already exists."
        ) from exc

    from app.core.nats_client import nats_client
    from app.core.subjects import TOPOLOGY_CABLE_ADDED, topology_cable_payload

    try:
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
    except Exception:
        _logger.warning("NATS publish failed for hardware event", exc_info=True)
    return conn


# ── Standalone hardware-connection delete (by relation ID) ───────────────────

hw_conn_router = APIRouter(tags=["hardware"])


@hw_conn_router.delete("/hardware-connections/{connection_id}", status_code=204)
async def delete_hardware_connection(
    connection_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_write_auth)] = None,
) -> None:
    """Delete a hardware-to-hardware connection by its ID."""
    from app.core.nats_client import nats_client
    from app.core.subjects import TOPOLOGY_CABLE_REMOVED

    try:
        removed = hardware_service.remove_hardware_connection(db, connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        await nats_client.publish(
            TOPOLOGY_CABLE_REMOVED,
            {
                "source_id": f"hw-{removed['source_hardware_id']}",
                "target_id": f"hw-{removed['target_hardware_id']}",
                "connection_id": connection_id,
            },
        )
    except Exception:
        _logger.warning("NATS publish failed for hardware event", exc_info=True)

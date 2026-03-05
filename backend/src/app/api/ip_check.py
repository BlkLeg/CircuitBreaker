"""Read-only IP conflict check endpoint — powers real-time inline validation."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.ip_reservation import check_ip_conflict

router = APIRouter(tags=["ip-check"])


class PortEntryIn(BaseModel):
    ip: str | None = None
    port: int | None = None
    protocol: str | None = "tcp"
    label: str | None = None


class IpCheckRequest(BaseModel):
    ip: str
    ports: list[PortEntryIn] | None = None
    exclude_entity_type: str | None = None
    exclude_entity_id: int | None = None


@router.post("/ip-check")
def check_ip(payload: IpCheckRequest, db: Session = Depends(get_db)):
    """Return any conflicts for the given IP address + optional port bindings.

    An empty ``conflicts`` list means the IP (and all port bindings) are available.
    This endpoint is intentionally unauthenticated so the frontend can call it
    inline while the user is still filling in a form — before submitting.
    """
    ports_as_dicts = (
        [pe.model_dump() for pe in payload.ports] if payload.ports else None
    )
    conflicts = check_ip_conflict(
        db,
        ip=payload.ip,
        ports=ports_as_dicts,
        exclude_entity_type=payload.exclude_entity_type,
        exclude_entity_id=payload.exclude_entity_id,
    )
    return {"conflicts": [c.to_dict() for c in conflicts]}

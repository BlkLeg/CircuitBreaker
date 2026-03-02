import logging

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Rack, Hardware
from app.schemas.rack import RackCreate, RackUpdate
from app.core.time import utcnow

_logger = logging.getLogger(__name__)


def _to_dict(rack: Rack, hardware_count: int = 0) -> dict:
    return {
        "id": rack.id,
        "name": rack.name,
        "height_u": rack.height_u,
        "location": rack.location,
        "notes": rack.notes,
        "hardware_count": hardware_count,
        "created_at": rack.created_at,
        "updated_at": rack.updated_at,
    }


def list_racks(db: Session) -> list[dict]:
    racks = db.execute(select(Rack)).scalars().all()
    result = []
    for rack in racks:
        hw_count = len(rack.hardware)
        result.append(_to_dict(rack, hw_count))
    return result


def get_rack(db: Session, rack_id: int) -> dict:
    rack = db.get(Rack, rack_id)
    if rack is None:
        raise ValueError(f"Rack {rack_id} not found")
    return _to_dict(rack, len(rack.hardware))


def create_rack(db: Session, payload: RackCreate) -> dict:
    rack = Rack(
        name=payload.name,
        height_u=payload.height_u,
        location=payload.location,
        notes=payload.notes,
    )
    db.add(rack)
    db.commit()
    db.refresh(rack)
    return _to_dict(rack, 0)


def update_rack(db: Session, rack_id: int, payload: RackUpdate) -> dict:
    rack = db.get(Rack, rack_id)
    if rack is None:
        raise ValueError(f"Rack {rack_id} not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(rack, field, value)
    rack.updated_at = utcnow()
    db.commit()
    db.refresh(rack)
    return _to_dict(rack, len(rack.hardware))


def delete_rack(db: Session, rack_id: int) -> None:
    rack = db.get(Rack, rack_id)
    if rack is None:
        raise ValueError(f"Rack {rack_id} not found")
    # Manually null-out rack_id on hardware (SQLite FK cascades unreliable
    # without PRAGMA foreign_keys=ON per-connection)
    for hw in db.execute(select(Hardware).where(Hardware.rack_id == rack_id)).scalars().all():
        hw.rack_id = None
    db.flush()
    db.delete(rack)
    db.commit()


def check_rack_overlap(
    db: Session,
    rack_id: int,
    rack_unit: int,
    u_height: int,
    exclude_hardware_id: int | None = None,
) -> list[dict]:
    """Check if placing a device at [rack_unit, rack_unit + u_height - 1] in the
    given rack conflicts with any existing hardware placement.

    Returns a list of conflicting hardware dicts (empty if no conflict).
    """
    new_top = rack_unit + u_height - 1
    stmt = select(Hardware).where(
        Hardware.rack_id == rack_id,
        Hardware.rack_unit.isnot(None),
        Hardware.u_height.isnot(None),
    )
    if exclude_hardware_id is not None:
        stmt = stmt.where(Hardware.id != exclude_hardware_id)
    conflicts = []
    for hw in db.execute(stmt).scalars().all():
        existing_bottom = hw.rack_unit
        existing_top = hw.rack_unit + hw.u_height - 1
        # Ranges overlap if new_bottom <= existing_top AND new_top >= existing_bottom
        if rack_unit <= existing_top and new_top >= existing_bottom:
            conflicts.append({
                "hardware_id": hw.id,
                "name": hw.name,
                "rack_unit": hw.rack_unit,
                "u_height": hw.u_height,
            })
    return conflicts

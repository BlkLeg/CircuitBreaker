import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.schemas.settings import AppSettingsUpdate

_DEFAULTS = dict(
    id=1,
    theme="dark",
    default_environment=None,
    show_experimental_features=False,
    api_base_url=None,
    map_default_filters=None,
    vendor_icon_mode="custom_files",
    environments='["prod","staging","dev"]',
    categories='[]',
    locations='[]',
    dock_order=None,
)


def get_or_create_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(**_DEFAULTS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_settings(db: Session, payload: AppSettingsUpdate) -> AppSettings:
    row = get_or_create_settings(db)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field in ("map_default_filters", "environments", "categories", "locations", "dock_order"):
            # Accept list/dict → serialize to JSON string; None → None
            if value is not None and not isinstance(value, str):
                value = json.dumps(value)
        setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def reset_settings(db: Session) -> AppSettings:
    row = get_or_create_settings(db)
    for field, value in _DEFAULTS.items():
        if field == "id":
            continue
        setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row

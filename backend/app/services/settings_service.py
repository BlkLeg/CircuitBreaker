import json
import secrets
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
    dock_hidden_items=None,
    show_page_hints=True,
    app_name="Circuit Breaker",
    favicon_path=None,
    login_logo_path=None,
    primary_color="#00d4ff",
    accent_colors='["#ff6b6b","#4ecdc4"]',
    theme_preset="cyberpunk-neon",
    custom_colors=None,
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
        if field == "branding":
            # Unpack nested branding config into flat columns
            if value is not None:
                if value.get("app_name") is not None:
                    row.app_name = value["app_name"]
                if value.get("primary_color") is not None:
                    row.primary_color = value["primary_color"]
                if value.get("accent_colors") is not None:
                    row.accent_colors = json.dumps(value["accent_colors"])
                # favicon_path and login_logo_path are only set via upload endpoints
            continue
        if field == "theme_colors":
            # Serialise ThemeColors dict → JSON string stored in custom_colors column.
            # Explicitly set to None when null so switching from custom to a named preset
            # clears the stale custom_colors from the DB.
            row.custom_colors = json.dumps(value) if value is not None else None
            continue
        if field in ("map_default_filters", "environments", "categories", "locations", "dock_order", "dock_hidden_items"):
            # Accept list/dict → serialize to JSON string; None → None
            if value is not None and not isinstance(value, str):
                value = json.dumps(value)
        setattr(row, field, value)
    # Auto-generate JWT secret when auth is being enabled for the first time
    if data.get("auth_enabled") and not row.jwt_secret:
        row.jwt_secret = secrets.token_hex(32)
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

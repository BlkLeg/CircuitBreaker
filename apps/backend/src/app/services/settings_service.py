"""Settings persistence and defaults.

SECRETS: Never log or expose jwt_secret, vault_key, CB_VAULT_KEY, or any
value from AppSettings that holds credentials. Use log_service.sanitise_diff
for any payload that might contain these.
"""

import json
import secrets
import zoneinfo

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.time import utcnow, utcnow_iso
from app.db.models import AppSettings, Log
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
    categories="[]",
    locations="[]",
    dock_order=None,
    dock_hidden_items=None,
    show_page_hints=True,
    show_header_widgets=True,
    show_time_widget=True,
    show_weather_widget=True,
    weather_location="Phoenix, AZ",
    language="en",
    app_name="Circuit Breaker",
    favicon_path=None,
    login_logo_path=None,
    login_bg_path=None,
    primary_color="#fe8019",
    accent_colors='["#fabd2f","#b8bb26"]',
    theme_preset="gruvbox-dark",
    custom_colors=None,
    discovery_enabled=False,
    discovery_auto_merge=False,
    discovery_default_cidr="",
    discovery_nmap_args="-sV -O --open -T4",
    discovery_snmp_community="",
    discovery_schedule_cron="",
    discovery_http_probe=True,
    discovery_retention_days=30,
    scan_ack_accepted=False,
    discovery_mode="safe",
    docker_discovery_enabled=False,
    docker_socket_path="/var/run/docker.sock",
    docker_sync_interval_minutes=5,
    graph_default_layout="dagre",
    map_title="Topology",
)


def get_or_create_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(**_DEFAULTS)
        row.jwt_secret = secrets.token_hex(32)
        db.add(row)
        db.commit()
        db.refresh(row)
    elif not row.jwt_secret:
        row.jwt_secret = secrets.token_hex(32)
        db.commit()
        db.refresh(row)
    return row


def update_settings(
    db: Session, payload: AppSettingsUpdate, *, user_id: int | None = None
) -> AppSettings:
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
        if field == "timezone":
            if value is not None and value != "UTC" and value not in zoneinfo.available_timezones():
                raise HTTPException(status_code=422, detail=f'Invalid timezone "{value}"')
            setattr(row, field, value)
            _write_timezone_log(db, value or "UTC", user_id=user_id)
            continue
        if field in (
            "map_default_filters",
            "environments",
            "categories",
            "locations",
            "dock_order",
            "dock_hidden_items",
        ):
            # Accept list/dict → serialize to JSON string; None → None
            if value is not None and not isinstance(value, str):
                value = json.dumps(value)
        elif field == "smtp_password":
            # Encrypt plaintext password before storing; empty string clears it
            from app.services.credential_vault import get_vault

            vault = get_vault()
            if value:
                row.smtp_password_enc = vault.encrypt(value)
            # If value is None we leave smtp_password_enc untouched so
            # callers can omit the field to keep the existing password.
            continue
        setattr(row, field, value)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def _write_timezone_log(db: Session, timezone: str, *, user_id: int | None = None) -> None:
    """Write a user-visible audit log entry when the timezone preference is changed."""
    from sqlalchemy import select

    from app.db.models import User

    actor_name = "system"
    actor_id: int | None = None
    actor_gravatar: str | None = None

    if user_id and user_id > 0:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user:
            actor_name = user.display_name or user.email
            actor_id = user.id
            actor_gravatar = user.gravatar_hash

    now_iso = utcnow_iso()
    log_entry = Log(
        level="info",
        category="settings",
        action="update_timezone",
        actor=actor_name,
        actor_name=actor_name,
        actor_id=actor_id,
        actor_gravatar_hash=actor_gravatar,
        details=f'Timezone updated to "{timezone}"',
        created_at_utc=now_iso,
    )
    db.add(log_entry)


def reset_settings(db: Session) -> AppSettings:
    row = get_or_create_settings(db)
    for field, value in _DEFAULTS.items():
        if field == "id":
            continue
        setattr(row, field, value)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def update_user_language(db: Session, user_id: int, language: str) -> None:
    db.execute(
        text("UPDATE users SET language = :lang WHERE id = :id"),
        {"lang": language, "id": user_id},
    )
    db.commit()


def get_user_language(db: Session, user_id: int) -> str:
    result = db.scalar(
        text("SELECT language FROM users WHERE id = :id"),
        {"id": user_id},
    )
    return result or "en"

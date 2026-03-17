import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.security import get_optional_user
from app.db.session import get_db
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate, SmtpUpdate
from app.services import settings_service
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["settings"])
_logger = logging.getLogger(__name__)


@router.get("", response_model=AppSettingsRead)
def get_settings(
    db: Session = Depends(get_db),
    user_id: int | None = Depends(get_optional_user),
) -> Any:
    """Return the current app settings, initializing defaults on first access."""
    settings = settings_service.get_or_create_settings(db)
    # Keep pre-bootstrap behavior (no jwt secret yet), but require auth after OOBE.
    if settings.jwt_secret and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return settings


@router.put("", response_model=AppSettingsRead)
def put_settings(
    payload: AppSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = require_role("admin"),
) -> Any:
    """Merge-update app settings. Only supplied fields are changed."""
    result = settings_service.update_settings(db, payload, user_id=user.id)
    if payload.rate_limit_profile is not None:
        from app.core.rate_limit import invalidate_rate_limit_profile_cache

        invalidate_rate_limit_profile_cache()
    from app.core.audit import log_audit

    log_audit(
        db, request, user_id=user.id, action="settings_update", resource="settings", status="ok"
    )
    return result


@router.post("/reset", response_model=AppSettingsRead)
def reset_settings(db: Session = Depends(get_db), _: Any = require_role("admin")) -> Any:
    """Reset all settings to factory defaults."""
    return settings_service.reset_settings(db)


@router.patch("/smtp", response_model=AppSettingsRead)
def patch_smtp(
    payload: SmtpUpdate,
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> Any:
    """Update SMTP configuration fields only; auto-encrypts password.

    Auto-enables SMTP when the caller provides a host and from-email but
    doesn't explicitly set smtp_enabled.  Entering SMTP configuration is a
    clear signal the user wants email delivery active.
    """
    data = payload.model_dump(exclude_unset=True)
    has_host = bool((data.get("smtp_host") or "").strip())
    has_from = bool((data.get("smtp_from_email") or "").strip())
    if has_host and has_from and "smtp_enabled" not in data:
        payload.smtp_enabled = True
    return settings_service.update_settings(db, payload)  # type: ignore[arg-type]


@router.post("/smtp/test")
async def test_smtp(
    send_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> dict[str, Any]:
    """Test SMTP connectivity and optionally send a test email to send_to."""
    from app.services.smtp_service import SmtpService

    cfg = settings_service.get_or_create_settings(db)
    if not cfg.smtp_host:
        return {"status": "error", "message": "SMTP host is not configured"}

    svc = SmtpService(cfg)
    if send_to:
        result = await svc.send_test_email(send_to)
    else:
        result = await svc.test_connection()

    cfg.smtp_last_test_at = datetime.utcnow().isoformat()
    cfg.smtp_last_test_status = result["status"]
    if result["status"] == "ok" and not cfg.smtp_enabled:
        cfg.smtp_enabled = True
    db.commit()
    return result


@router.get("/oauth", response_model=dict)
def get_oauth_settings(
    db: Session = Depends(get_db), _: Any = require_role("admin")
) -> dict[str, Any]:
    settings = get_or_create_settings(db)
    providers: dict = settings.oauth_providers if isinstance(settings.oauth_providers, dict) else {}
    oidc_raw = settings.oidc_providers if isinstance(settings.oidc_providers, (list, dict)) else []
    for p in providers.values():
        p["client_secret_set"] = bool(p.get("client_secret_enc") or p.get("client_secret"))
        p.pop("client_secret", None)
        p.pop("client_secret_enc", None)
    # Strip raw OIDC secrets from GET response
    oidc_items = oidc_raw if isinstance(oidc_raw, list) else list(oidc_raw.values())
    for p in oidc_items:
        p["client_secret_set"] = bool(p.get("client_secret_enc") or p.get("client_secret"))
        p.pop("client_secret", None)
        p.pop("client_secret_enc", None)
    return {"oauth_providers": providers, "oidc_providers": oidc_items}


@router.patch("/oauth")
def update_oauth_settings(
    payload: dict[str, Any], db: Session = Depends(get_db), _: Any = require_role("admin")
) -> dict[str, Any]:
    settings = get_or_create_settings(db)
    existing: dict = settings.oauth_providers if isinstance(settings.oauth_providers, dict) else {}
    for provider_name, cfg in payload.get("oauth_providers", {}).items():
        if provider_name not in existing:
            existing[provider_name] = {}
        existing[provider_name].update({k: v for k, v in cfg.items() if k != "client_secret_set"})
        if cfg.get("client_secret"):
            try:
                from app.services.credential_vault import get_vault

                existing[provider_name]["client_secret_enc"] = get_vault().encrypt(
                    cfg["client_secret"]
                )
                existing[provider_name].pop("client_secret", None)
            except Exception as e:
                _logger.debug("OAuth vault encrypt failed (keeping plain): %s", e, exc_info=True)
    settings.oauth_providers = existing
    if "oidc_providers" in payload:
        oidc_raw = payload["oidc_providers"]
        oidc_list = oidc_raw if isinstance(oidc_raw, list) else list(oidc_raw.values())
        existing_oidc_raw = (
            settings.oidc_providers if isinstance(settings.oidc_providers, (list, dict)) else []
        )
        existing_oidc = (
            existing_oidc_raw
            if isinstance(existing_oidc_raw, list)
            else list(existing_oidc_raw.values())
        )
        # Build lookup of existing entries by slug/name to preserve encrypted secrets
        existing_by_slug: dict = {}
        for ep in existing_oidc:
            key = ep.get("slug") or ep.get("name", "")
            if key:
                existing_by_slug[key] = ep
        merged: list = []
        for p in oidc_list:
            entry = dict(p)
            slug = entry.get("slug") or entry.get("name", "")
            prev = existing_by_slug.get(slug, {})
            if entry.get("client_secret"):
                # New secret supplied — encrypt it
                try:
                    from app.services.credential_vault import get_vault

                    entry["client_secret_enc"] = get_vault().encrypt(entry["client_secret"])
                    entry.pop("client_secret", None)
                except Exception as e:
                    _logger.debug("OIDC vault encrypt failed (keeping plain): %s", e, exc_info=True)
            elif not entry.get("client_secret"):
                # No new secret — preserve existing encrypted value if present
                entry.pop("client_secret", None)
                if prev.get("client_secret_enc"):
                    entry["client_secret_enc"] = prev["client_secret_enc"]
            merged.append(entry)
        settings.oidc_providers = merged
    db.commit()
    return {"status": "ok"}

import logging
from datetime import UTC, datetime

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


def _oauth_providers_dict(settings) -> dict:
    raw = settings.oauth_providers
    return dict(raw) if isinstance(raw, dict) else {}


def _oidc_providers_list(settings) -> list[dict]:
    raw = settings.oidc_providers
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [dict(item) for item in raw.values() if isinstance(item, dict)]
    return []


def _set_encrypted_client_secret(target: dict, plain_secret: str, log_context: str) -> None:
    try:
        from app.services.credential_vault import get_vault

        target["client_secret_enc"] = get_vault().encrypt(plain_secret)
        target.pop("client_secret", None)
    except Exception as err:
        _logger.debug(
            "%s vault encrypt failed (keeping plain): %s", log_context, err, exc_info=True
        )


def _merge_oauth_payload(existing: dict, oauth_payload: dict) -> dict:
    merged = dict(existing)
    for provider_name, cfg in oauth_payload.items():
        if not isinstance(cfg, dict):
            continue
        entry = dict(merged.get(provider_name) or {})
        entry.update({key: value for key, value in cfg.items() if key != "client_secret_set"})
        client_secret = cfg.get("client_secret")
        if isinstance(client_secret, str) and client_secret:
            _set_encrypted_client_secret(entry, client_secret, "OAuth")
        merged[provider_name] = entry
    return merged


def _merge_oidc_payload(existing_oidc: list[dict], oidc_payload: object) -> list[dict]:
    incoming = _incoming_oidc_items(oidc_payload)
    if not incoming:
        return existing_oidc

    existing_by_slug: dict[str, dict] = {}
    for provider in existing_oidc:
        key = provider.get("slug") or provider.get("name", "")
        if isinstance(key, str) and key:
            existing_by_slug[key] = provider

    merged: list[dict] = []
    for provider in incoming:
        merged.append(_merge_single_oidc_entry(provider, existing_by_slug))
    return merged


def _incoming_oidc_items(oidc_payload: object) -> list[dict]:
    if isinstance(oidc_payload, dict):
        return [dict(item) for item in oidc_payload.values() if isinstance(item, dict)]
    if isinstance(oidc_payload, list):
        return [dict(item) for item in oidc_payload if isinstance(item, dict)]
    return []


def _merge_single_oidc_entry(provider: dict, existing_by_slug: dict[str, dict]) -> dict:
    entry = dict(provider)
    slug = entry.get("slug") or entry.get("name", "")
    prev = existing_by_slug.get(slug, {}) if isinstance(slug, str) else {}
    client_secret = entry.get("client_secret")

    if isinstance(client_secret, str) and client_secret:
        _set_encrypted_client_secret(entry, client_secret, "OIDC")
        return entry

    entry.pop("client_secret", None)
    prev_secret = prev.get("client_secret_enc")
    if prev_secret:
        entry["client_secret_enc"] = prev_secret
    return entry


def _with_secret_flags_oauth(providers: dict) -> dict:
    response: dict = {}
    for name, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        entry = dict(cfg)
        entry["client_secret_set"] = bool(
            entry.get("client_secret_enc") or entry.get("client_secret")
        )
        entry.pop("client_secret", None)
        entry.pop("client_secret_enc", None)
        response[name] = entry
    return response


def _with_secret_flags_oidc(oidc_items: list[dict]) -> list[dict]:
    response: list[dict] = []
    for provider in oidc_items:
        entry = dict(provider)
        entry["client_secret_set"] = bool(
            entry.get("client_secret_enc") or entry.get("client_secret")
        )
        entry.pop("client_secret", None)
        entry.pop("client_secret_enc", None)
        response.append(entry)
    return response


@router.get("", response_model=AppSettingsRead)
def get_settings(
    db: Session = Depends(get_db),
    user_id: int | None = Depends(get_optional_user),
):
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
    user=require_role("admin"),
):
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
def reset_settings(db: Session = Depends(get_db), _=require_role("admin")):
    """Reset all settings to factory defaults."""
    return settings_service.reset_settings(db)


@router.patch("/smtp", response_model=AppSettingsRead)
def patch_smtp(
    payload: SmtpUpdate,
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
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
    _=require_role("admin"),
):
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

    cfg.smtp_last_test_at = datetime.now(UTC).isoformat()
    cfg.smtp_last_test_status = result["status"]
    if result["status"] == "ok" and not cfg.smtp_enabled:
        cfg.smtp_enabled = True
    db.commit()
    return result


@router.get("/oauth", response_model=dict)
def get_oauth_settings(db: Session = Depends(get_db), _=require_role("admin")):
    settings = get_or_create_settings(db)
    providers = _with_secret_flags_oauth(_oauth_providers_dict(settings))
    oidc_items = _with_secret_flags_oidc(_oidc_providers_list(settings))
    return {"oauth_providers": providers, "oidc_providers": oidc_items}


@router.patch("/oauth")
def update_oauth_settings(payload: dict, db: Session = Depends(get_db), _=require_role("admin")):
    settings = get_or_create_settings(db)
    existing = _oauth_providers_dict(settings)
    oauth_payload = payload.get("oauth_providers")
    if isinstance(oauth_payload, dict):
        settings.oauth_providers = _merge_oauth_payload(existing, oauth_payload)
    else:
        settings.oauth_providers = existing

    if "oidc_providers" in payload:
        settings.oidc_providers = _merge_oidc_payload(
            _oidc_providers_list(settings), payload["oidc_providers"]
        )

    db.commit()
    return {"status": "ok"}

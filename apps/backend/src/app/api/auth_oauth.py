"""OAuth / OIDC login flows: GitHub, Google, and generic OIDC (e.g. Authentik)."""

import base64
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.core.time import utcnow_iso
from app.db.models import AppSettings, OAuthState, User
from app.db.session import get_db
from app.services.credential_vault import get_vault

router = APIRouter(prefix="/auth", tags=["oauth"])
_logger = logging.getLogger(__name__)

_INVALID_STATE = "Invalid OAuth state"
_STATE_EXPIRED = "OAuth state expired. Please try signing in again."
_OAUTH_STATE_TTL = timedelta(minutes=10)
_STAGE_TOKEN_EXCHANGE = "token exchange"
_STAGE_USER_LOOKUP = "user lookup"
_STAGE_DISCOVERY = "discovery"


# ---------------------------------------------------------------------------
# Public discovery endpoint (no auth required)
# ---------------------------------------------------------------------------


@router.get("/oauth/providers")
def list_oauth_providers(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the list of enabled OAuth/OIDC providers for the login page."""
    settings = db.query(AppSettings).first()
    providers: list[dict] = []
    if settings and settings.oauth_providers:
        oauth_data = settings.oauth_providers if isinstance(settings.oauth_providers, dict) else {}
        for name, cfg in oauth_data.items():
            if cfg.get("enabled") and cfg.get("client_id"):
                providers.append({"name": name, "type": "oauth"})
    if settings and settings.oidc_providers:
        raw = settings.oidc_providers if isinstance(settings.oidc_providers, (list, dict)) else []
        items = raw if isinstance(raw, list) else raw.values()
        for p in items:
            if p.get("enabled") and p.get("client_id"):
                slug = p.get("slug") or p.get("name", "oidc")
                providers.append({"name": slug, "label": p.get("label", slug), "type": "oidc"})
    return {"providers": providers}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_oauth_config(db: Session, provider: str) -> dict:
    """Load provider config from AppSettings.oauth_providers JSON."""
    settings = db.query(AppSettings).first()
    if not settings or not settings.oauth_providers:
        raise HTTPException(400, f"OAuth provider '{provider}' not configured")
    providers = settings.oauth_providers if isinstance(settings.oauth_providers, dict) else {}
    cfg = providers.get(provider)
    if not cfg or not cfg.get("enabled"):
        raise HTTPException(400, f"OAuth provider '{provider}' not enabled")
    return cast(dict, cfg)


def _get_oidc_config(db: Session, provider_slug: str) -> dict:
    settings = db.query(AppSettings).first()
    if not settings or not settings.oidc_providers:
        raise HTTPException(400, f"OIDC provider '{provider_slug}' not configured")
    providers = settings.oidc_providers if isinstance(settings.oidc_providers, list) else []
    cfg = next(
        (p for p in providers if p.get("slug") == provider_slug or p.get("name") == provider_slug),
        None,
    )
    if not cfg or not cfg.get("enabled"):
        raise HTTPException(400, f"OIDC provider '{provider_slug}' not enabled")
    return cast(dict, cfg)


def _ensure_provider_enabled(
    db: Session, provider_name: str, cfg: dict, *, provider_type: str
) -> None:
    """Persist the provider as enabled so it remains visible on the login screen.

    This is a defensive write for successful OAuth/OIDC flows. It preserves any
    existing secret fields already stored in AppSettings while ensuring the
    provider stays enabled for future sign-ins after logout/bootstrap.
    """
    settings = db.query(AppSettings).first()
    if not settings:
        return

    changed = False
    if provider_type == "oauth":
        providers: dict = (
            settings.oauth_providers if isinstance(settings.oauth_providers, dict) else {}
        )
        entry = dict(providers.get(provider_name) or {})
        if entry.get("enabled") is not True:
            entry["enabled"] = True
            changed = True
        if cfg.get("client_id") and entry.get("client_id") != cfg.get("client_id"):
            entry["client_id"] = cfg["client_id"]
            changed = True
        providers[provider_name] = entry
        if changed:
            settings.oauth_providers = providers
    else:
        raw = settings.oidc_providers if isinstance(settings.oidc_providers, (list, dict)) else []
        items = raw if isinstance(raw, list) else list(raw.values())
        slug = cfg.get("slug") or cfg.get("name") or provider_name
        matched = False
        updated_items: list[dict] = []
        for item in items:
            item_slug = item.get("slug") or item.get("name")
            if item_slug == slug:
                merged = dict(item)
                if merged.get("enabled") is not True:
                    merged["enabled"] = True
                    changed = True
                for key in ("client_id", "discovery_url", "label", "name", "slug"):
                    if cfg.get(key) and merged.get(key) != cfg.get(key):
                        merged[key] = cfg[key]
                        changed = True
                updated_items.append(merged)
                matched = True
            else:
                updated_items.append(item)
        if not matched:
            new_entry = {
                k: v
                for k, v in cfg.items()
                if k in {"slug", "name", "label", "client_id", "discovery_url"}
            }
            new_entry["enabled"] = True
            updated_items.append(new_entry)
            changed = True
        if changed:
            settings.oidc_providers = updated_items

    if changed:
        try:
            db.commit()
        except Exception:
            _logger.warning("Failed to commit provider enable flag", exc_info=True)
            # Non-critical — don't block login


def _get_app_base_url(db: Session, request: Request | None = None) -> str:
    settings = db.query(AppSettings).first()
    api_base_url = getattr(settings, "api_base_url", None) if settings else None
    if api_base_url:
        return str(api_base_url).rstrip("/")
    if request is not None:
        proto = (
            (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
        )
        host = (
            (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
            .split(",")[0]
            .strip()
        )
        if host:
            return f"{proto}://{host}".rstrip("/")
    return "http://localhost:8080"


def _is_state_expired(created_at: str) -> bool:
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return datetime.now(UTC) - parsed > _OAUTH_STATE_TTL


def _pop_state_or_400(db: Session, state: str, provider_filter: Any) -> OAuthState:
    oauth_state = db.query(OAuthState).filter(OAuthState.state == state, provider_filter).first()
    if not oauth_state:
        raise HTTPException(400, _INVALID_STATE)
    expired = _is_state_expired(oauth_state.created_at)
    db.delete(oauth_state)
    db.commit()
    if expired:
        raise HTTPException(400, _STATE_EXPIRED)
    return oauth_state


def _get_user_oauth_tokens(user: User) -> dict | None:
    """Return decrypted OAuth tokens for user, or None.

    Handles both encrypted and legacy plaintext.
    """
    raw = user.oauth_tokens
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (TypeError, ValueError):
        pass
    try:
        vault = get_vault()
        plain = vault.decrypt(raw)
        data = json.loads(plain)
        if isinstance(data, dict):
            return cast(dict, data)
        return None
    except (RuntimeError, ValueError, TypeError):
        return None


def _upsert_oauth_user(
    db: Session,
    email: str,
    display_name: str,
    provider: str,
    oauth_tokens: dict,
    avatar_url: str | None = None,
) -> tuple[User, bool]:
    """Upsert an OAuth user. Returns (user, is_new)."""
    user = db.query(User).filter(User.email == email).first()
    is_new = user is None
    if is_new:
        from app.core.security import hash_password

        user = User(
            email=email,
            display_name=display_name,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            provider=provider,
            is_active=True,
            role="viewer",
            created_at=utcnow_iso(),
            profile_photo=avatar_url,
        )
        db.add(user)
    else:
        assert user is not None
        user.provider = provider
        try:
            vault = get_vault()
            user.oauth_tokens = vault.encrypt(json.dumps(oauth_tokens))
        except RuntimeError:
            # Vault not initialized; do not store tokens in plaintext
            user.oauth_tokens = None
        # Always refresh the avatar so it stays current
        if avatar_url:
            user.profile_photo = avatar_url
    try:
        db.commit()
    except Exception:
        _logger.exception("OAuth user upsert commit failed")
        raise HTTPException(
            status_code=502, detail="Authentication failed. Please try again."
        ) from None
    db.refresh(user)
    assert user is not None
    return user, is_new


def _issue_jwt_and_redirect(
    user: User, base_url: str, db: Session, request: Request
) -> RedirectResponse:
    """Issue a CB JWT for the user and redirect to frontend with token."""
    from app.core.auth_cookie import set_auth_cookie_on_response
    from app.services.auth_service import _make_token
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import record_session

    cfg = get_or_create_settings(db)
    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    response = RedirectResponse(url=f"{base_url}/?oauth_token={token}", status_code=302)
    set_auth_cookie_on_response(request, response, token, cfg.session_timeout_hours)
    return response


def _bootstrap_redirect_or_none(
    user: User,
    base_url: str,
    provider_name: str,
    db: Session,
    request: Request,
) -> RedirectResponse | None:
    """Redirect to OOBE bootstrap flow whenever setup hasn't been completed yet.

    This handles both fresh accounts and retries with the same OAuth provider/email —
    until OOBE bootstrap is complete the user must finish setup before using the app.
    """
    import secrets as _secrets_mod

    from app.core.auth_cookie import set_auth_cookie_on_response
    from app.services.auth_service import _make_token
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import record_session

    cfg = get_or_create_settings(db)
    # Bootstrap is already done — let the normal login flow take over.
    if cfg.auth_enabled:
        return None
    # Ensure a jwt_secret exists so we can issue the bootstrap token.
    if not cfg.jwt_secret:
        cfg.jwt_secret = _secrets_mod.token_hex(32)
        db.commit()
    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    response = RedirectResponse(
        url=f"{base_url}/oobe?oauth_token={token}&bootstrap=1&provider={provider_name}",
        status_code=302,
    )
    set_auth_cookie_on_response(request, response, token, cfg.session_timeout_hours)
    return response


def _client_secret(cfg: dict) -> str:
    if cfg.get("client_secret"):
        return str(cfg["client_secret"])
    enc = cfg.get("client_secret_enc", "")
    if not enc:
        return ""
    try:
        from app.services.credential_vault import get_vault

        return str(get_vault().decrypt(enc))
    except Exception:
        return str(enc)


def _json_or_502(resp: httpx.Response, provider: str, stage: str) -> dict:
    try:
        resp.raise_for_status()
        return cast(dict, resp.json())
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{provider} OAuth {stage} failed. Please try again.",
        ) from exc


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


@router.get("/oauth/github")
@limiter.limit(lambda: get_limit("auth"))
def github_authorize(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> RedirectResponse:
    cfg = _get_oauth_config(db, "github")
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(state=state, provider="github", created_at=datetime.now(UTC).isoformat()))
    db.commit()
    params = urlencode({"client_id": cfg["client_id"], "state": state, "scope": "user:email"})
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}", status_code=302)


@router.get("/oauth/github/callback")
@limiter.limit(lambda: get_limit("auth"))
async def github_callback(
    request: Request, response: Response, code: str, state: str, db: Session = Depends(get_db)
) -> RedirectResponse:
    _pop_state_or_400(db, state, OAuthState.provider == "github")

    cfg = _get_oauth_config(db, "github")
    _ensure_provider_enabled(db, "github", cfg, provider_type="oauth")
    base_url = _get_app_base_url(db, request)

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": cfg["client_id"],
                "client_secret": _client_secret(cfg),
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
        token_data = _json_or_502(token_resp, "GitHub", _STAGE_TOKEN_EXCHANGE)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(400, "Failed to obtain access token from GitHub")

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10.0,
        )
        gh_user = _json_or_502(user_resp, "GitHub", _STAGE_USER_LOOKUP)
        email = gh_user.get("email")

        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            emails = _json_or_502(emails_resp, "GitHub", "email lookup")
            email = next(
                (e["email"] for e in emails if e.get("primary") and e.get("verified")), None
            )
            if not email and emails:
                email = emails[0]["email"]

    if not email:
        raise HTTPException(400, "Could not obtain email from GitHub account")

    display_name = gh_user.get("name") or gh_user.get("login", "")
    avatar_url = gh_user.get("avatar_url")
    user, is_new = _upsert_oauth_user(
        db,
        email,
        display_name,
        "github",
        {"access_token": access_token},
        avatar_url=avatar_url,
    )
    bootstrap_redir = _bootstrap_redirect_or_none(user, base_url, "github", db, request)
    if bootstrap_redir:
        return bootstrap_redir
    return _issue_jwt_and_redirect(user, base_url, db, request)


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


@router.get("/oauth/google")
@limiter.limit(lambda: get_limit("auth"))
def google_authorize(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> RedirectResponse:
    cfg = _get_oauth_config(db, "google")
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(state=state, provider="google", created_at=datetime.now(UTC).isoformat()))
    db.commit()
    base_url = _get_app_base_url(db, request)
    redirect_uri = f"{base_url}/api/v1/auth/oauth/google/callback"
    params = urlencode(
        {
            "client_id": cfg["client_id"],
            "state": state,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
        }
    )
    return RedirectResponse(
        f"https://accounts.google.com/o/oauth2/v2/auth?{params}", status_code=302
    )


@router.get("/oauth/google/callback")
@limiter.limit(lambda: get_limit("auth"))
async def google_callback(
    request: Request, response: Response, code: str, state: str, db: Session = Depends(get_db)
) -> RedirectResponse:
    _pop_state_or_400(db, state, OAuthState.provider == "google")

    cfg = _get_oauth_config(db, "google")
    _ensure_provider_enabled(db, "google", cfg, provider_type="oauth")
    base_url = _get_app_base_url(db, request)
    redirect_uri = f"{base_url}/api/v1/auth/oauth/google/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": cfg["client_id"],
                "client_secret": _client_secret(cfg),
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10.0,
        )
        token_data = _json_or_502(token_resp, "Google", _STAGE_TOKEN_EXCHANGE)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(400, "Failed to obtain access token from Google")

        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        g_user = _json_or_502(user_resp, "Google", _STAGE_USER_LOOKUP)

    email = g_user.get("email")
    if not email:
        raise HTTPException(400, "Could not obtain email from Google account")
    display_name = g_user.get("name", "")
    avatar_url = g_user.get("picture")
    user, is_new = _upsert_oauth_user(
        db,
        email,
        display_name,
        "google",
        {"access_token": access_token},
        avatar_url=avatar_url,
    )
    bootstrap_redir = _bootstrap_redirect_or_none(user, base_url, "google", db, request)
    if bootstrap_redir:
        return bootstrap_redir
    return _issue_jwt_and_redirect(user, base_url, db, request)


# ---------------------------------------------------------------------------
# Generic OIDC (Authentik, Keycloak, etc.)
# ---------------------------------------------------------------------------


@router.get("/oauth/oidc/{provider_slug}")
@limiter.limit(lambda: get_limit("auth"))
async def oidc_authorize(
    request: Request, response: Response, provider_slug: str, db: Session = Depends(get_db)
) -> RedirectResponse:
    cfg = _get_oidc_config(db, provider_slug)
    state = secrets.token_urlsafe(32)

    # PKCE
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )

    db.add(
        OAuthState(
            state=state,
            provider=f"oidc:{provider_slug}:{verifier}",
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    db.commit()

    async with httpx.AsyncClient() as client:
        disc_resp = await client.get(cfg["discovery_url"], timeout=10.0)
        disc = _json_or_502(disc_resp, "OIDC", _STAGE_DISCOVERY)

    base_url = _get_app_base_url(db, request)
    redirect_uri = f"{base_url}/api/v1/auth/oauth/oidc/{provider_slug}/callback"
    params = urlencode(
        {
            "client_id": cfg["client_id"],
            "state": state,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return RedirectResponse(f"{disc['authorization_endpoint']}?{params}", status_code=302)


@router.get("/oauth/oidc/{provider_slug}/callback")
@limiter.limit(lambda: get_limit("auth"))
async def oidc_callback(
    request: Request,
    response: Response,
    provider_slug: str,
    code: str,
    state: str,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    oauth_state = _pop_state_or_400(db, state, OAuthState.provider.like(f"oidc:{provider_slug}:%"))

    verifier = oauth_state.provider.split(":", 2)[2]

    cfg = _get_oidc_config(db, provider_slug)
    _ensure_provider_enabled(db, provider_slug, cfg, provider_type="oidc")
    base_url = _get_app_base_url(db, request)
    redirect_uri = f"{base_url}/api/v1/auth/oauth/oidc/{provider_slug}/callback"

    async with httpx.AsyncClient() as client:
        disc_resp = await client.get(cfg["discovery_url"], timeout=10.0)
        disc = _json_or_502(disc_resp, "OIDC", _STAGE_DISCOVERY)
        token_resp = await client.post(
            disc["token_endpoint"],
            data={
                "client_id": cfg["client_id"],
                "client_secret": _client_secret(cfg),
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10.0,
        )
        token_data = _json_or_502(token_resp, "OIDC", _STAGE_TOKEN_EXCHANGE)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(400, "Failed to obtain access token from OIDC provider")

        userinfo_resp = await client.get(
            disc["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        userinfo = _json_or_502(userinfo_resp, "OIDC", _STAGE_USER_LOOKUP)

    email = userinfo.get("email")
    if not email:
        raise HTTPException(400, "OIDC provider did not return email")
    display_name = userinfo.get("name") or userinfo.get("preferred_username", "")
    avatar_url = userinfo.get("picture")
    user, is_new = _upsert_oauth_user(
        db,
        email,
        display_name,
        "oidc",
        {"access_token": access_token},
        avatar_url=avatar_url,
    )
    bootstrap_redir = _bootstrap_redirect_or_none(user, base_url, provider_slug, db, request)
    if bootstrap_redir:
        return bootstrap_redir
    return _issue_jwt_and_redirect(user, base_url, db, request)

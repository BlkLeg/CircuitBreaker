"""Auth endpoints: FastAPI-Users routers plus backward-compat legacy routes.

API tokens (machine–machine): POST /auth/api-token, GET /auth/api-tokens,
DELETE /auth/api-tokens/:id. Admin only; token shown once on create.

Mounts:
  /api/v1/auth/jwt              — login, logout (FastAPI-Users OAuth2 format)
  /api/v1/auth                  — register, forgot-password, reset-password
  /api/v1/users                 — /me, PATCH /me (FastAPI-Users)
  /api/v1/auth/me               — backward-compat GET returning UserProfile
  /api/v1/auth/login            — backward-compat JSON login returning {token, user}
  /api/v1/auth/force-change-password — redeem change_token and set new password
  /api/v1/auth/me/avatar        — profile photo + display_name update (custom)
"""

import hashlib
import json
import logging
import secrets
from datetime import timedelta
from typing import Annotated, Any

import jwt as _jwt
import pyotp
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.auth_cookie import auth_response_with_cookie, clear_auth_cookie_response
from app.core.rate_limit import get_limit, limiter
from app.core.rbac import effective_scopes, require_role
from app.core.security import (
    _extract_token,
    create_salted_api_token_hash,
    create_token,
    get_optional_user,
    hash_password,
    require_auth_always,
)
from app.core.time import utcnow, utcnow_iso
from app.core.token_scopes import GRANTABLE_SCOPES, SCOPE_PRESETS
from app.core.users import auth_backend, fastapi_users
from app.db.models import APIToken, User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    UserProfile,
    UserRead,
    UserUpdate,
    VaultResetRequest,
)
from app.services.auth_service import _to_profile
from app.services.settings_service import get_or_create_settings

_logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# FastAPI-Users routers (mounted in main.py with their own prefixes)
# ---------------------------------------------------------------------------

auth_jwt_router = fastapi_users.get_auth_router(auth_backend)
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)

# Phase 6.5: Self-service sessions and password (mounted at /api/v1/users)
user_me_router = APIRouter(tags=["users"])


# ---------------------------------------------------------------------------
# Registration (gated by registration_open)
# ---------------------------------------------------------------------------


class AcceptInviteRequest(BaseModel):
    token: str
    password: str | None = None
    password_hash: str | None = None
    display_name: str | None = None

    @model_validator(mode="after")
    def require_password_or_hash(self) -> "AcceptInviteRequest":
        if not self.password and not self.password_hash:
            raise ValueError("Either password or password_hash is required")
        if self.password and self.password_hash:
            raise ValueError("Provide only one of password or password_hash")
        return self


class DemoAuthResponse(BaseModel):
    token: str
    user: UserProfile
    expires_at: str


@router.post("/accept-invite", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def accept_invite_endpoint(
    request: Request,
    response: Response,
    payload: AcceptInviteRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Claim an invite and create a user account. Public endpoint."""
    from app.schemas.auth import AuthResponse
    from app.services.auth_service import _make_token, _to_profile
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import accept_invite as svc_accept_invite

    password_or_hash = (
        payload.password_hash if payload.password_hash is not None else payload.password
    )
    if password_or_hash is None:
        raise HTTPException(status_code=422, detail="password or password_hash is required")
    user = svc_accept_invite(db, payload.token, password_or_hash, payload.display_name)
    cfg = get_or_create_settings(db)
    token = _make_token(user, cfg)
    body = AuthResponse(token=token, user=_to_profile(user)).model_dump()
    return auth_response_with_cookie(request, token, body, cfg.session_timeout_hours)


@router.post("/register", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def register_user(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Register a new user. Gated by AppSettings.registration_open."""
    from app.services.auth_service import register as svc_register

    cfg = get_or_create_settings(db)
    if not getattr(cfg, "registration_open", True):
        raise HTTPException(status_code=403, detail="Registration is currently closed")
    password_or_hash = (
        payload.password_hash if payload.password_hash is not None else payload.password
    )
    if password_or_hash is None:
        raise HTTPException(status_code=422, detail="password or password_hash is required")
    result = svc_register(db, payload.email, password_or_hash, cfg, payload.display_name)
    body = result.model_dump()
    return auth_response_with_cookie(request, result.token, body, cfg.session_timeout_hours)


# ---------------------------------------------------------------------------
# Password reset (Redis-backed, replaces FastAPI-Users reset router)
# ---------------------------------------------------------------------------


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str | None = None
    password_hash: str | None = None

    @model_validator(mode="after")
    def require_password_or_hash(self) -> "ResetPasswordRequest":
        if not self.password and not self.password_hash:
            raise ValueError("Either password or password_hash is required")
        if self.password and self.password_hash:
            raise ValueError("Provide only one of password or password_hash")
        return self


# INC-08. "Temporarily disabled" told a locked-out user nothing they could act on, and
# "temporarily" promised a return that is not planned. Both paths named here are real:
# POST /admin/users/{id}/reset-password issues a one-time password and forces a change at
# the next login, and Reset With Vault Key is on the login page for the case where no
# administrator can sign in either.
_EMAIL_RESET_DISABLED_DETAIL = (
    "Self-service password reset is not available. Ask an administrator to reset your "
    "password from Users → Reset Password; they will give you a one-time temporary "
    "password and you will be asked to choose a new one at your next login. If no "
    "administrator can sign in, use Reset With Vault Key from the login page."
)


@router.post("/forgot-password", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
async def forgot_password(
    request: Request,
    response: Response,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> None:
    """Email-based reset is disabled; users must use vault-key recovery."""
    _logger.info("[auth] forgot-password requested while email reset is disabled")
    raise HTTPException(status_code=410, detail=_EMAIL_RESET_DISABLED_DETAIL)


@router.post("/reset-password", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
async def reset_password(
    request: Request,
    response: Response,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> None:
    """Email-based reset is disabled; users must use vault-key recovery."""
    _logger.info("[auth] reset-password requested while email reset is disabled")
    raise HTTPException(status_code=410, detail=_EMAIL_RESET_DISABLED_DETAIL)


# ---------------------------------------------------------------------------
# Demo session
# ---------------------------------------------------------------------------


@router.post("/demo", response_model=DemoAuthResponse, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def create_demo_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    """Create a one-hour demo read-only session."""
    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")

    expires_at = utcnow() + timedelta(hours=1)
    demo_user = User(
        email=f"demo-{utcnow().timestamp():.0f}@local.demo",
        hashed_password=hash_password("demo-session-not-loginable"),
        display_name="Demo User",
        language=cfg.language or "en",
        is_admin=False,
        is_superuser=False,
        is_active=True,
        created_at=utcnow_iso(),
        role="demo",
        scopes='["read:*"]',
        demo_expires=expires_at,
        provider="local",
    )
    db.add(demo_user)
    db.commit()
    db.refresh(demo_user)

    token = create_token(
        demo_user.id,
        cfg.jwt_secret,
        1,
        role="demo",
        scopes=["read:*"],
        demo_expires=expires_at.isoformat(),
    )
    body = DemoAuthResponse(
        token=token, user=_to_profile(demo_user), expires_at=expires_at.isoformat()
    ).model_dump()
    return auth_response_with_cookie(request, token, body, 1)


# ---------------------------------------------------------------------------
# Backward-compat login: JSON body, returns {token, user}
# ---------------------------------------------------------------------------


@router.post("/login", tags=["auth"], response_model=None)
@limiter.limit(lambda: get_limit("auth"))
def login_compat(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any] | Response:
    """JSON login returning {token, user} for legacy clients.

    When the user has force_password_change=True, returns
    {"requires_change": true, "change_token": "<jwt>"} instead of a full
    session token.  The client must POST that token to /auth/force-change-password.
    """
    from app.core.security import verify_password
    from app.core.time import utcnow
    from app.services.auth_service import login as svc_login
    from app.services.user_service import reset_login_attempts

    cfg = get_or_create_settings(db)
    ip = request.client.host if request.client else None

    password_or_hash = (
        payload.password_hash if payload.password_hash is not None else payload.password
    )
    if password_or_hash is None:
        raise HTTPException(status_code=422, detail="password or password_hash is required")

    # Early check for force_password_change before creating a full session.
    email_norm = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    if user and user.locked_until and user.locked_until > utcnow():
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if (
        user
        and verify_password(password_or_hash, user.hashed_password)
        and getattr(user, "force_password_change", False)
    ):
        reset_login_attempts(db, user)
        change_token = _jwt.encode(
            {
                "user_id": user.id,
                "aud": "cb:change-password",
                "exp": utcnow() + timedelta(hours=1),
            },
            cfg.jwt_secret or "",
            algorithm="HS256",
        )
        return {"requires_change": True, "change_token": change_token}

    # MFA challenge: if credentials are valid and MFA is enabled, issue
    # a short-lived mfa_token rather than a full session JWT.
    if user and getattr(user, "mfa_enabled", False):
        from app.core.security import verify_password as _vp

        if _vp(password_or_hash, user.hashed_password):
            from app.services.user_service import reset_login_attempts as _rla

            _rla(db, user)
            mfa_token = _jwt.encode(
                {
                    "user_id": user.id,
                    "aud": "cb:mfa-challenge",
                    "exp": utcnow() + timedelta(minutes=5),
                },
                cfg.jwt_secret or "",
                algorithm="HS256",
            )
            return {"requires_mfa": True, "mfa_token": mfa_token}

    result = svc_login(db, payload.email, password_or_hash, cfg, ip, request=request)
    body = result.model_dump()
    return auth_response_with_cookie(request, result.token, body, cfg.session_timeout_hours)


class ForceChangePasswordRequest(BaseModel):
    change_token: str
    new_password: str | None = None
    new_password_hash: str | None = None

    @model_validator(mode="after")
    def require_new_password_or_hash(self) -> "ForceChangePasswordRequest":
        if not self.new_password and not self.new_password_hash:
            raise ValueError("Either new_password or new_password_hash is required")
        if self.new_password and self.new_password_hash:
            raise ValueError("Provide only one of new_password or new_password_hash")
        return self


@router.post("/force-change-password", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def force_change_password(
    request: Request,
    response: Response,
    payload: ForceChangePasswordRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Redeem a change_token (from force_password_change login) and set a new password.

    Returns a normal {token, user} auth response so the user is logged in immediately
    after successfully changing their password.
    """
    from app.services.auth_service import reset_local_user_password

    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")

    try:
        payload_jwt = _jwt.decode(
            payload.change_token,
            cfg.jwt_secret,
            algorithms=["HS256"],
            audience="cb:change-password",
        )
    except _jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status_code=401, detail="Change token has expired — please log in again"
        ) from err
    except _jwt.PyJWTError as err:
        raise HTTPException(status_code=401, detail="Invalid change token") from err

    user_id = payload_jwt.get("user_id")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    _reject_if_locked_out(user)

    from app.services.auth_service import _make_token, _to_profile
    from app.services.user_service import record_session

    new_password_or_hash = (
        payload.new_password_hash if payload.new_password_hash is not None else payload.new_password
    )
    if new_password_or_hash is None:
        raise HTTPException(status_code=422, detail="new_password or new_password_hash is required")
    reset_local_user_password(
        db, user, new_password_or_hash, source="force_change", update_last_login=True
    )
    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    from app.schemas.auth import AuthResponse

    body = AuthResponse(token=token, user=_to_profile(user)).model_dump()
    return auth_response_with_cookie(request, token, body, cfg.session_timeout_hours)


# ---------------------------------------------------------------------------
# API tokens (machine–machine, admin only, token shown once on create)
# ---------------------------------------------------------------------------


class CreateAPITokenRequest(BaseModel):
    label: str | None = None
    expires_at: str | None = None  # ISO datetime or None for no expiry
    # B4 / INC-04: omitted means "the same access I have", NOT [] — an empty
    # list stored here is exactly what made every UI-created token 403.
    scopes: list[str] | None = None

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        from app.core.token_scopes import validate_scopes

        return validate_scopes(v)


_SERVICE_ACCOUNT_LABEL_PREFIX = "[Service Account] "


class APITokenItem(BaseModel):
    id: int
    label: str | None
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    scopes: list[str] = []
    created_by: int | None = None
    created_by_name: str | None = None
    is_service_account: bool = False


class CreateAPITokenResponse(BaseModel):
    token: str
    id: int
    label: str | None
    expires_at: str | None


class CreateServiceAccountRequest(BaseModel):
    label: str | None = None
    scopes: list[str] = ["read:*"]
    expires_at: str | None = None  # ISO datetime or None for no expiry

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v: list[str]) -> list[str]:
        from app.core.token_scopes import validate_scopes

        return validate_scopes(v)


@router.post("/service-account", response_model=CreateAPITokenResponse, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def create_service_account(
    request: Request,
    payload: CreateServiceAccountRequest,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> CreateAPITokenResponse:
    """Create a scoped service account token (JWT).

    Admin-only. Generates a JWT with embedded scopes and stores a salted
    hash in the APIToken table for tracking and revocation.
    """
    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")

    expires_delta = None
    expires_at_dt = None
    if payload.expires_at:
        try:
            from datetime import datetime

            expires_at_dt = datetime.fromisoformat(payload.expires_at.replace("Z", "+00:00"))
            now = utcnow()
            if expires_at_dt <= now:
                raise ValueError("Expiry must be in the future")
            diff = expires_at_dt - now
            expires_delta = int(diff.total_seconds() / 3600)
        except (ValueError, TypeError) as err:
            raise HTTPException(
                status_code=400, detail=str(err) or "expires_at must be ISO 8601 datetime"
            ) from err

    token = create_token(
        0,  # user_id=0: service-account sentinel
        cfg.jwt_secret,
        expires_delta or 8760,  # Default 1 year
        scopes=payload.scopes,
        extra_claims={"label": payload.label},
    )

    token_hash = create_salted_api_token_hash(token)
    api_token = APIToken(
        token_hash=token_hash,
        label=f"[Service Account] {payload.label or 'unnamed'}",
        created_by=current_user.id,
        scopes=payload.scopes,
        expires_at=expires_at_dt,
    )
    db.add(api_token)
    db.commit()
    db.refresh(api_token)

    return CreateAPITokenResponse(
        token=token,
        id=api_token.id,
        label=api_token.label,
        expires_at=api_token.expires_at.isoformat() if api_token.expires_at else None,
    )


@router.post("/api-token", response_model=CreateAPITokenResponse, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def create_api_token(
    request: Request,
    response: Response,
    payload: CreateAPITokenRequest,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> CreateAPITokenResponse:
    """Create a long-lived API token. The raw token is returned once; store it securely."""

    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")
    raw_token = secrets.token_urlsafe(32)
    token_hash = create_salted_api_token_hash(raw_token)
    expires_at = None
    if payload.expires_at:
        try:
            from datetime import datetime

            expires_at = datetime.fromisoformat(payload.expires_at.replace("Z", "+00:00"))
        except (ValueError, TypeError) as err:
            raise HTTPException(
                status_code=400, detail="expires_at must be ISO 8601 datetime"
            ) from err
    api_token = APIToken(
        token_hash=token_hash,
        label=payload.label,
        created_by=current_user.id,
        scopes=payload.scopes if payload.scopes else sorted(effective_scopes(current_user)),
        expires_at=expires_at,
    )
    db.add(api_token)
    db.commit()
    db.refresh(api_token)
    return CreateAPITokenResponse(
        token=raw_token,
        id=api_token.id,
        label=api_token.label,
        expires_at=payload.expires_at,
    )


@router.get("/scopes", tags=["auth"])
def list_grantable_scopes(
    _user: Annotated[User, require_role("admin")],
) -> dict:
    """The scopes a token may be granted, and the presets the UI offers."""
    return {
        "scopes": [
            {"scope": scope, "description": description}
            for scope, description in sorted(GRANTABLE_SCOPES.items())
        ],
        "presets": SCOPE_PRESETS,
    }


@router.get("/api-tokens", response_model=list[APITokenItem], tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def list_api_tokens(
    request: Request,
    response: Response,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
    scope: str = Query("mine", pattern="^(mine|all)$"),
) -> list[APITokenItem]:
    """List API tokens. `scope=all` returns the whole install's inventory."""
    q = db.query(APIToken)
    if scope == "mine":
        q = q.filter(APIToken.created_by == current_user.id)
    tokens = q.order_by(APIToken.created_at.desc()).all()

    creator_ids = {t.created_by for t in tokens if t.created_by is not None}
    creators: dict[int, str] = {}
    if creator_ids:
        for uid, email, name in db.query(User.id, User.email, User.display_name).filter(
            User.id.in_(creator_ids)
        ):
            creators[uid] = name or email

    return [
        APITokenItem(
            id=t.id,
            label=t.label,
            created_at=t.created_at.isoformat() if t.created_at else "",
            expires_at=t.expires_at.isoformat() if t.expires_at else None,
            last_used_at=t.last_used_at.isoformat() if t.last_used_at else None,
            scopes=list(t.scopes or []),
            created_by=t.created_by,
            created_by_name=creators.get(t.created_by),
            is_service_account=bool(t.label and t.label.startswith(_SERVICE_ACCOUNT_LABEL_PREFIX)),
        )
        for t in tokens
    ]


@router.delete("/api-tokens/{token_id}", status_code=204, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def revoke_api_token(
    request: Request,
    response: Response,
    token_id: int,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> None:
    """Revoke an API token. Any admin may revoke any token."""
    api_token = db.get(APIToken, token_id)
    if not api_token:
        raise HTTPException(status_code=404, detail="API token not found")
    db.delete(api_token)
    db.commit()
    from app.core.security import invalidate_token_cache

    invalidate_token_cache()


@router.post("/api-tokens/{token_id}/rotate", response_model=CreateAPITokenResponse, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def rotate_api_token(
    request: Request,
    response: Response,
    token_id: int,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> CreateAPITokenResponse:
    """Replace a token's secret, keeping its label, scopes and expiry."""
    old = db.get(APIToken, token_id)
    if not old:
        raise HTTPException(status_code=404, detail="API token not found")

    raw_token = secrets.token_urlsafe(32)
    replacement = APIToken(
        token_hash=create_salted_api_token_hash(raw_token),
        label=old.label,
        created_by=current_user.id,
        scopes=list(old.scopes or []),
        expires_at=old.expires_at,
    )
    db.add(replacement)
    db.delete(old)
    db.commit()
    db.refresh(replacement)

    from app.core.security import invalidate_token_cache

    invalidate_token_cache()

    return CreateAPITokenResponse(
        token=raw_token,
        id=replacement.id,
        label=replacement.label,
        expires_at=replacement.expires_at.isoformat() if replacement.expires_at else None,
    )


@router.post("/vault-reset", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def vault_reset_password(
    request: Request,
    response: Response,
    payload: VaultResetRequest,
    db: Session = Depends(get_db),
) -> Response:
    from app.services.auth_service import vault_reset_password as svc_vault_reset_password

    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")
    new_password_or_hash = (
        payload.new_password_hash if payload.new_password_hash is not None else payload.new_password
    )
    if new_password_or_hash is None:
        raise HTTPException(status_code=422, detail="new_password or new_password_hash is required")
    result = svc_vault_reset_password(
        db,
        payload.email,
        payload.vault_key,
        new_password_or_hash,
        cfg,
        request=request,
    )
    from app.schemas.auth import AuthResponse as _AuthResponse

    if not isinstance(result, _AuthResponse):
        raise HTTPException(status_code=500, detail="Unexpected response from vault reset")
    body = result.model_dump()
    return auth_response_with_cookie(request, result.token, body, cfg.session_timeout_hours)


# ---------------------------------------------------------------------------
# Backward-compat: GET /api/v1/auth/me
# ---------------------------------------------------------------------------


def _reject_if_locked_out(user: User) -> None:
    """Refuse a challenge-token redemption for a user who is currently locked out.

    Login checks the lockout, but the tokens login *hands out* — the
    force-change token and the MFA token — were only checked for signature,
    expiry, and `is_active`. A caller holding one issued just before the lockout
    (or who triggers the lockout by brute-forcing the second factor) could keep
    redeeming it for a full session, which is the one thing lockout exists to
    stop. The 401 matches login's generic reply so it discloses nothing extra.
    """
    locked_until = getattr(user, "locked_until", None)
    if locked_until and locked_until > utcnow():
        raise HTTPException(status_code=401, detail="Invalid email or password")


@router.get("/me", response_model=UserProfile, tags=["auth"])
def get_me_compat(
    request: Request,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> UserProfile:
    """Backward-compat endpoint returning the current user's profile."""
    if user_id == 0:
        return UserProfile(
            id=0,
            email="api-token@system",
            is_admin=True,
            is_superuser=True,
            role="admin",
            scopes=["read:*", "write:*", "delete:*", "admin:*"],
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    try:
        return _to_profile(user)
    except Exception as e:
        _logger.exception("auth/me: failed to build profile for user_id=%s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Failed to load profile") from e


# ---------------------------------------------------------------------------
# Logout: revoke session and clear cookie
# ---------------------------------------------------------------------------


@router.post("/logout", status_code=204, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    """Revoke the caller's session (Bearer or cookie) and clear the session cookie."""
    from app.db.models import UserSession

    raw_token = _extract_token(request)
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        session = (
            db.query(UserSession)
            .filter(UserSession.jwt_token_hash == token_hash)
            .filter(UserSession.revoked == False)  # noqa: E712
            .first()
        )
        if session:
            session.revoked = True
            db.commit()
            from app.core.security import invalidate_session_cache

            invalidate_session_cache(raw_token)
    return clear_auth_cookie_response()


# ---------------------------------------------------------------------------
# Account self-deletion
# ---------------------------------------------------------------------------


@router.delete("/me", status_code=204, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def delete_me(
    request: Request,
    response: Response,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> Response:
    """Delete the authenticated user's own account."""
    from app.services.auth_service import delete_account

    delete_account(db, user_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Profile photo upload (custom — FastAPI-Users doesn't handle file uploads)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 6.5: Self-service sessions and password
# ---------------------------------------------------------------------------


class SessionItem(BaseModel):
    id: int
    ip_address: str | None
    user_agent: str | None
    created_at: str
    expires_at: str
    revoked: bool


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    current_password_hash: str | None = None
    new_password: str | None = None
    new_password_hash: str | None = None

    @model_validator(mode="after")
    def require_passwords_or_hashes(self) -> "ChangePasswordRequest":
        if not self.current_password and not self.current_password_hash:
            raise ValueError("Either current_password or current_password_hash is required")
        if self.current_password and self.current_password_hash:
            raise ValueError("Provide only one of current_password or current_password_hash")
        if not self.new_password and not self.new_password_hash:
            raise ValueError("Either new_password or new_password_hash is required")
        if self.new_password and self.new_password_hash:
            raise ValueError("Provide only one of new_password or new_password_hash")
        return self


@user_me_router.get("/me/sessions", response_model=list[SessionItem])
def list_my_sessions(
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> list[SessionItem]:
    """List the current user's active sessions."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id == 0:
        return []
    from app.core.time import utcnow
    from app.db.models import UserSession

    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .filter(UserSession.revoked == False)  # noqa: E712
        .filter(UserSession.expires_at > utcnow())
        .order_by(UserSession.created_at.desc())
        .all()
    )
    return [
        SessionItem(
            id=s.id,
            ip_address=s.ip_address,
            user_agent=(s.user_agent or "")[:200] if s.user_agent else None,
            created_at=s.created_at.isoformat() if s.created_at else "",
            expires_at=s.expires_at.isoformat() if s.expires_at else "",
            revoked=s.revoked,
        )
        for s in sessions
    ]


@user_me_router.delete("/me/sessions/{session_id}", status_code=204)
@limiter.limit(lambda: get_limit("auth"))
def revoke_session(
    request: Request,
    response: Response,
    session_id: int,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> None:
    """Revoke a specific session."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.user_service import revoke_session as svc_revoke

    if not svc_revoke(db, session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")


@user_me_router.delete("/me/sessions", status_code=204)
@limiter.limit(lambda: get_limit("auth"))
def revoke_all_other_sessions(
    request: Request,
    response: Response,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> None:
    """Revoke all sessions except the current one."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id == 0:
        return
    from app.services.user_service import _hash_token, revoke_all_sessions

    token = _extract_token(request)
    except_hash = _hash_token(token) if token else None
    revoke_all_sessions(db, user_id, except_token_hash=except_hash)


@user_me_router.patch("/me/password", status_code=204)
@limiter.limit(lambda: get_limit("auth"))
def change_password(
    request: Request,
    response: Response,
    payload: ChangePasswordRequest,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> None:
    """Change the current user's password."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id == 0:
        raise HTTPException(status_code=403, detail="Service account has no password")
    from app.core.security import verify_password
    from app.services.auth_service import _is_client_hash, _validate_password

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    current_or_hash = (
        payload.current_password_hash
        if payload.current_password_hash is not None
        else payload.current_password
    )
    if current_or_hash is None:
        raise HTTPException(
            status_code=422, detail="current_password or current_password_hash is required"
        )
    if not verify_password(current_or_hash, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_or_hash = (
        payload.new_password_hash if payload.new_password_hash is not None else payload.new_password
    )
    if new_or_hash is None:
        raise HTTPException(status_code=422, detail="new_password or new_password_hash is required")
    if not _is_client_hash(new_or_hash):
        _validate_password(new_or_hash)
    from app.core.security import hash_password
    from app.services.user_service import _hash_token, revoke_all_sessions

    user.hashed_password = hash_password(new_or_hash)

    token = _extract_token(request)
    except_hash = _hash_token(token) if token else None
    revoke_all_sessions(db, user_id, except_token_hash=except_hash)

    db.commit()

    from app.services.log_service import write_log

    write_log(
        db,
        action="password_changed",
        entity_type="user",
        entity_id=user_id,
        entity_name=user.email,
        severity="info",
        category="auth",
        actor_name=user.display_name or user.email,
        actor_id=user_id,
        details='{"source": "self_change"}',
    )


# ---------------------------------------------------------------------------
# Profile photo upload (custom — FastAPI-Users doesn't handle file uploads)
# ---------------------------------------------------------------------------


@router.put("/me/avatar", response_model=UserProfile, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
async def upload_avatar(
    request: Request,
    response: Response,
    display_name: str | None = Form(None),
    profile_photo: UploadFile | None = File(None),
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> UserProfile:
    from app.services.auth_service import update_profile

    result = await update_profile(
        db, user_id, display_name=display_name, profile_photo=profile_photo
    )
    return result


# ---------------------------------------------------------------------------
# MFA / TOTP endpoints
# ---------------------------------------------------------------------------

_BACKUP_CODE_COUNT = 8


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str  # 6-digit TOTP or one-time backup code


class MfaConfirmRequest(BaseModel):
    code: str  # TOTP code to prove ownership before disabling / activating


class MfaBackupCodesResponse(BaseModel):
    backup_codes: list[str]


def _generate_backup_codes() -> list[str]:
    return [secrets.token_hex(5).upper() for _ in range(_BACKUP_CODE_COUNT)]


def _store_backup_codes(user: User, raw_codes: list[str]) -> None:
    from app.core.security import hash_password as _hash

    user.backup_codes = json.dumps([_hash(c) for c in raw_codes])


def _verify_mfa_confirmation_code(user: User, code: str) -> bool:
    code = code.strip()
    if user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            return True

    if user.backup_codes:
        from app.core.security import verify_password as _vp

        stored = json.loads(user.backup_codes)
        for i, hashed in enumerate(stored):
            if _vp(code, hashed):
                stored.pop(i)
                user.backup_codes = json.dumps(stored)
                return True
    return False


@router.post("/mfa/setup", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_setup(
    request: Request,
    response: Response,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Generate a new TOTP secret and return the provisioning URI.

    The caller must confirm the secret by calling /mfa/verify before it is
    activated.  The secret is stored immediately so subsequent calls to this
    endpoint rotate it.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")

    secret = pyotp.random_base32()
    user.totp_secret = secret
    # mfa_enabled stays False until the user confirms with /mfa/verify
    db.commit()

    totp = pyotp.TOTP(secret)
    app_name = "CircuitBreaker"
    uri = totp.provisioning_uri(name=user.email, issuer_name=app_name)
    return {"totp_uri": uri, "secret": secret}


@router.post("/mfa/activate", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_activate(
    request: Request,
    response: Response,
    payload: MfaConfirmRequest,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> Response:
    """Confirm a newly generated TOTP secret and enable MFA."""
    from app.services.auth_service import _make_token, _to_profile
    from app.services.user_service import record_session, revoke_token_session

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first")

    cfg = get_or_create_settings(db)
    code = payload.code.strip()
    totp = pyotp.TOTP(user.totp_secret)

    if not totp.verify(code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    raw_codes = _generate_backup_codes()
    _store_backup_codes(user, raw_codes)
    user.mfa_enabled = True
    db.commit()

    token = _make_token(user, cfg)
    current_token = _extract_token(request)
    if current_token:
        revoke_token_session(db, current_token.strip())
    record_session(db, user, request, token, cfg)
    from app.core.audit import log_audit

    log_audit(db, request, user_id=user.id, action="mfa_enabled", resource="auth", status="ok")

    from app.schemas.auth import AuthResponse

    body = AuthResponse(token=token, user=_to_profile(user), backup_codes=raw_codes).model_dump()
    return auth_response_with_cookie(request, token, body, cfg.session_timeout_hours)


@router.post("/mfa/verify", tags=["auth"])
@limiter.limit(lambda: get_limit("mfa_verify"))
def mfa_verify(
    request: Request,
    response: Response,
    payload: MfaVerifyRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Exchange a valid TOTP code + mfa_token for a full session JWT.

    Also used to *activate* MFA after a fresh /mfa/setup call: if the user is
    not yet fully authenticated, the mfa_token from /login is required.
    """
    from app.services.auth_service import _make_token, _to_profile
    from app.services.user_service import (
        record_failed_login,
        record_session,
        reset_login_attempts,
    )

    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")

    try:
        tok = _jwt.decode(
            payload.mfa_token,
            cfg.jwt_secret,
            algorithms=["HS256"],
            audience="cb:mfa-challenge",
        )
    except _jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="MFA token expired — please log in again"
        ) from None
    except _jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid MFA token") from None

    user = db.get(User, tok.get("user_id"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    _reject_if_locked_out(user)

    code = payload.code.strip()

    # Try TOTP first
    if user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            # A completed second factor ends the login attempt, so the counter
            # that the failures below feed is cleared here.
            reset_login_attempts(db, user)
            token = _make_token(user, cfg)
            record_session(db, user, request, token, cfg)
            from app.schemas.auth import AuthResponse

            body = AuthResponse(token=token, user=_to_profile(user)).model_dump()
            return auth_response_with_cookie(request, token, body, cfg.session_timeout_hours)

    # Try backup codes
    if user.backup_codes:
        from app.core.security import verify_password as _vp

        stored = json.loads(user.backup_codes)
        for i, hashed in enumerate(stored):
            if _vp(code, hashed):
                stored.pop(i)
                user.backup_codes = json.dumps(stored)
                db.commit()
                reset_login_attempts(db, user)
                token = _make_token(user, cfg)
                record_session(db, user, request, token, cfg)
                from app.schemas.auth import AuthResponse

                body = AuthResponse(token=token, user=_to_profile(user)).model_dump()
                return auth_response_with_cookie(request, token, body, cfg.session_timeout_hours)

    # A wrong second factor is a failed login attempt and must count toward the
    # same lockout the password step feeds. Previously only the rate limiter
    # stood here, so an attacker holding a valid mfa_token could grind TOTP
    # codes at the limiter's pace indefinitely and never lock the account.
    record_failed_login(db, user, cfg)

    from app.core.audit import log_audit

    log_audit(
        db,
        request,
        user_id=user.id,
        action="mfa_verify_failed",
        resource="auth",
        status="fail",
        details=f"Failed MFA attempt from {request.client.host if request.client else 'unknown'}",
    )
    raise HTTPException(status_code=401, detail="Invalid or expired MFA code")


@router.post("/mfa/disable", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_disable(
    request: Request,
    response: Response,
    payload: MfaConfirmRequest,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Disable MFA for the authenticated user.

    Requires either a valid TOTP code or one of the user's backup codes
    to prevent disabling MFA without physical possession of the device.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    if not _verify_mfa_confirmation_code(user, payload.code):
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    user.mfa_enabled = False
    user.totp_secret = None
    user.backup_codes = None
    db.commit()
    from app.core.audit import log_audit

    log_audit(db, request, user_id=user_id, action="mfa_disabled", resource="auth", status="ok")
    return {"detail": "MFA disabled successfully"}


@router.post("/mfa/backup-codes/regenerate", response_model=MfaBackupCodesResponse, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_regenerate_backup_codes(
    request: Request,
    response: Response,
    payload: MfaConfirmRequest,
    user_id: int = Depends(require_auth_always),
    db: Session = Depends(get_db),
) -> MfaBackupCodesResponse:
    """Replace existing MFA backup codes after re-verifying user possession."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFA must be enabled first")

    if not _verify_mfa_confirmation_code(user, payload.code):
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    raw_codes = _generate_backup_codes()
    _store_backup_codes(user, raw_codes)
    db.commit()

    from app.core.audit import log_audit

    log_audit(
        db,
        request,
        user_id=user_id,
        action="mfa_backup_codes_regenerated",
        resource="auth",
        status="ok",
    )
    return MfaBackupCodesResponse(backup_codes=raw_codes)

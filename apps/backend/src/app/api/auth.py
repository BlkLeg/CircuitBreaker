"""Auth endpoints: FastAPI-Users routers plus backward-compat legacy routes.

Mounts:
  /api/v1/auth/jwt              — login, logout (FastAPI-Users OAuth2 format)
  /api/v1/auth                  — register, forgot-password, reset-password
  /api/v1/users                 — /me, PATCH /me (FastAPI-Users)
  /api/v1/auth/me               — backward-compat GET returning UserProfile
  /api/v1/auth/login            — backward-compat JSON login returning {token, user}
  /api/v1/auth/force-change-password — redeem change_token and set new password
  /api/v1/auth/me/avatar        — profile photo + display_name update (custom)
"""

import json
import secrets
from datetime import timedelta

import jwt as _jwt
import pyotp
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.core.security import create_token, get_optional_user, hash_password
from app.core.time import utcnow, utcnow_iso
from app.core.users import auth_backend, fastapi_users
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    UserProfile,
    UserRead,
    UserUpdate,
    VaultResetRequest,
)
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# FastAPI-Users routers (mounted in main.py with their own prefixes)
# ---------------------------------------------------------------------------

auth_jwt_router = fastapi_users.get_auth_router(auth_backend)
reset_password_router = fastapi_users.get_reset_password_router()
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)

# Phase 6.5: Self-service sessions and password (mounted at /api/v1/users)
user_me_router = APIRouter(tags=["users"])


# ---------------------------------------------------------------------------
# Registration (gated by registration_open)
# ---------------------------------------------------------------------------


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    display_name: str | None = None


class DemoAuthResponse(BaseModel):
    token: str
    user: UserProfile
    expires_at: str


@router.post("/accept-invite", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def accept_invite_endpoint(
    request: Request,
    payload: AcceptInviteRequest,
    db: Session = Depends(get_db),
):
    """Claim an invite and create a user account. Public endpoint."""
    from app.schemas.auth import AuthResponse
    from app.services.auth_service import _make_token, _to_profile
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import accept_invite as svc_accept_invite

    user = svc_accept_invite(db, payload.token, payload.password, payload.display_name)
    cfg = get_or_create_settings(db)
    token = _make_token(user, cfg)
    return AuthResponse(token=token, user=_to_profile(user))


@router.post("/register", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def register_user(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user. Gated by AppSettings.registration_open."""
    from app.services.auth_service import register as svc_register

    cfg = get_or_create_settings(db)
    if not getattr(cfg, "registration_open", True):
        raise HTTPException(status_code=403, detail="Registration is currently closed")
    return svc_register(db, payload.email, payload.password, cfg, payload.display_name)


@router.post("/demo", response_model=DemoAuthResponse, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def create_demo_session(
    request: Request,
    db: Session = Depends(get_db),
):
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
    return DemoAuthResponse(
        token=token, user=_to_profile(demo_user), expires_at=expires_at.isoformat()
    )


# ---------------------------------------------------------------------------
# Backward-compat login: JSON body, returns {token, user}
# ---------------------------------------------------------------------------


@router.post("/login", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def login_compat(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
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

    # Early check for force_password_change before creating a full session.
    email_norm = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    if (
        user
        and verify_password(payload.password, user.hashed_password)
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

        if _vp(payload.password, user.hashed_password):
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

    return svc_login(db, payload.email, payload.password, cfg, ip, request=request)


class ForceChangePasswordRequest(BaseModel):
    change_token: str
    new_password: str


@router.post("/force-change-password", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def force_change_password(
    request: Request,
    payload: ForceChangePasswordRequest,
    db: Session = Depends(get_db),
):
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

    from app.services.auth_service import _make_token, _to_profile
    from app.services.user_service import record_session

    reset_local_user_password(
        db, user, payload.new_password, source="force_change", update_last_login=True
    )
    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    from app.schemas.auth import AuthResponse

    return AuthResponse(token=token, user=_to_profile(user))


@router.post("/vault-reset", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def vault_reset_password(
    request: Request,
    payload: VaultResetRequest,
    db: Session = Depends(get_db),
):
    from app.services.auth_service import vault_reset_password as svc_vault_reset_password

    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")
    return svc_vault_reset_password(
        db,
        payload.email,
        payload.vault_key,
        payload.new_password,
        cfg,
        request=request,
    )


# ---------------------------------------------------------------------------
# Backward-compat: GET /api/v1/auth/me
# ---------------------------------------------------------------------------


def _to_profile(user: User) -> UserProfile:
    photo_url = f"/uploads/profiles/{user.profile_photo}" if user.profile_photo else None
    role = getattr(user, "role", None) or ("admin" if user.is_admin else "viewer")
    try:
        scopes = json.loads(getattr(user, "scopes", "[]") or "[]")
        if not isinstance(scopes, list):
            scopes = []
    except Exception:
        scopes = []
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        gravatar_hash=user.gravatar_hash,
        is_admin=user.is_admin,
        is_superuser=user.is_superuser,
        language=user.language or "en",
        profile_photo_url=photo_url,
        role=role,
        scopes=[str(s) for s in scopes if str(s).strip()],
    )


@router.get("/me", response_model=UserProfile, tags=["auth"])
def get_me_compat(
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Backward-compat endpoint returning the current user's profile."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
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
    return _to_profile(user)


# ---------------------------------------------------------------------------
# Backward-compat logout
# ---------------------------------------------------------------------------


@router.post("/logout", status_code=204, tags=["auth"])
def logout_compat(
    request: Request,
    db: Session = Depends(get_db),
):
    """Revoke the caller's active session so session_count stays accurate."""
    import hashlib

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[len("Bearer ") :].strip()
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        from app.db.models import UserSession

        session = (
            db.query(UserSession)
            .filter(UserSession.jwt_token_hash == token_hash)
            .filter(UserSession.revoked == False)  # noqa: E712
            .first()
        )
        if session:
            session.revoked = True
            db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Account self-deletion
# ---------------------------------------------------------------------------


@router.delete("/me", status_code=204, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def delete_me(
    request: Request,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Delete the authenticated user's own account."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
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
    current_password: str
    new_password: str


@user_me_router.get("/me/sessions", response_model=list[SessionItem])
def list_my_sessions(
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
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
    session_id: int,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
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
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Revoke all sessions except the current one."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id == 0:
        return
    from app.services.user_service import _hash_token, revoke_all_sessions

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[len("Bearer ") :] if auth_header.startswith("Bearer ") else None
    except_hash = _hash_token(token) if token else None
    revoke_all_sessions(db, user_id, except_token_hash=except_hash)


@user_me_router.patch("/me/password", status_code=204)
@limiter.limit(lambda: get_limit("auth"))
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id == 0:
        raise HTTPException(status_code=403, detail="Service account has no password")
    from app.core.security import verify_password
    from app.services.auth_service import _validate_password

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    _validate_password(payload.new_password)
    from app.core.security import hash_password

    user.hashed_password = hash_password(payload.new_password)
    db.commit()


# ---------------------------------------------------------------------------
# Profile photo upload (custom — FastAPI-Users doesn't handle file uploads)
# ---------------------------------------------------------------------------


@router.put("/me/avatar", response_model=UserProfile, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
async def upload_avatar(
    request: Request,
    display_name: str | None = Form(None),
    profile_photo: UploadFile | None = File(None),
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
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


@router.post("/mfa/setup", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_setup(
    request: Request,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Generate a new TOTP secret and return the provisioning URI.

    The caller must confirm the secret by calling /mfa/verify before it is
    activated.  The secret is stored immediately so subsequent calls to this
    endpoint rotate it.
    """
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

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
    payload: MfaConfirmRequest,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Confirm a newly generated TOTP secret and enable MFA."""
    from app.core.security import hash_password as _hash
    from app.services.auth_service import _make_token, _to_profile
    from app.services.user_service import record_session

    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
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

    raw_codes = [secrets.token_hex(5).upper() for _ in range(_BACKUP_CODE_COUNT)]
    user.backup_codes = json.dumps([_hash(c) for c in raw_codes])
    user.mfa_enabled = True
    db.commit()

    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    from app.core.audit import log_audit

    log_audit(db, request, user_id=user.id, action="mfa_enabled", resource="auth", status="ok")

    from app.schemas.auth import AuthResponse

    return AuthResponse(token=token, user=_to_profile(user), backup_codes=raw_codes)


@router.post("/mfa/verify", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_verify(
    request: Request,
    payload: MfaVerifyRequest,
    db: Session = Depends(get_db),
):
    """Exchange a valid TOTP code + mfa_token for a full session JWT.

    Also used to *activate* MFA after a fresh /mfa/setup call: if the user is
    not yet fully authenticated, the mfa_token from /login is required.
    """
    from app.services.auth_service import _make_token, _to_profile
    from app.services.user_service import record_session

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

    code = payload.code.strip()

    # Try TOTP first
    if user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            # Normal MFA login
            token = _make_token(user, cfg)
            record_session(db, user, request, token, cfg)
            from app.schemas.auth import AuthResponse

            return AuthResponse(token=token, user=_to_profile(user))

    # Try backup codes
    if user.backup_codes:
        from app.core.security import verify_password as _vp

        stored = json.loads(user.backup_codes)
        for i, hashed in enumerate(stored):
            if _vp(code, hashed):
                stored.pop(i)
                user.backup_codes = json.dumps(stored)
                db.commit()
                token = _make_token(user, cfg)
                record_session(db, user, request, token, cfg)
                from app.schemas.auth import AuthResponse

                return AuthResponse(token=token, user=_to_profile(user))

    raise HTTPException(status_code=401, detail="Invalid or expired MFA code")


@router.post("/mfa/disable", tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def mfa_disable(
    request: Request,
    payload: MfaConfirmRequest,
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Disable MFA for the authenticated user.

    Requires either a valid TOTP code or one of the user's backup codes
    to prevent disabling MFA without physical possession of the device.
    """
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    code = payload.code.strip()
    verified = False

    if user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            verified = True

    if not verified and user.backup_codes:
        from app.core.security import verify_password as _vp

        stored = json.loads(user.backup_codes)
        for i, hashed in enumerate(stored):
            if _vp(code, hashed):
                stored.pop(i)
                user.backup_codes = json.dumps(stored)
                verified = True
                break

    if not verified:
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    user.mfa_enabled = False
    user.totp_secret = None
    user.backup_codes = None
    db.commit()
    from app.core.audit import log_audit

    log_audit(db, request, user_id=user_id, action="mfa_disabled", resource="auth", status="ok")
    return {"detail": "MFA disabled successfully"}

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

from datetime import timedelta

import jwt as _jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.core.security import get_optional_user
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


@router.post("/accept-invite", tags=["auth"])
def accept_invite_endpoint(
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
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user. Gated by AppSettings.registration_open."""
    from app.services.auth_service import register as svc_register

    cfg = get_or_create_settings(db)
    if not getattr(cfg, "registration_open", True):
        raise HTTPException(status_code=403, detail="Registration is currently closed")
    return svc_register(db, payload.email, payload.password, cfg, payload.display_name)


# ---------------------------------------------------------------------------
# Backward-compat login: JSON body, returns {token, user}
# ---------------------------------------------------------------------------


@router.post("/login", tags=["auth"])
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

    return svc_login(db, payload.email, payload.password, cfg, ip, request=request)


class ForceChangePasswordRequest(BaseModel):
    change_token: str
    new_password: str


@router.post("/force-change-password", tags=["auth"])
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
        return UserProfile(id=0, email="api-token@system", is_admin=True, is_superuser=True)
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
def delete_me(
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
def revoke_session(
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
def change_password(
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
async def upload_avatar(
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

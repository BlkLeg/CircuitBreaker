"""Auth endpoints: FastAPI-Users routers plus backward-compat legacy routes.

Mounts:
  /api/v1/auth/jwt      — login, logout (FastAPI-Users OAuth2 format)
  /api/v1/auth          — register, forgot-password, reset-password
  /api/v1/users         — /me, PATCH /me (FastAPI-Users)
  /api/v1/auth/me       — backward-compat GET returning UserProfile
  /api/v1/auth/login    — backward-compat JSON login returning {token, user}
  /api/v1/auth/me/avatar — profile photo + display_name update (custom)
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

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
)
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# FastAPI-Users routers (mounted in main.py with their own prefixes)
# ---------------------------------------------------------------------------

auth_jwt_router = fastapi_users.get_auth_router(auth_backend)
reset_password_router = fastapi_users.get_reset_password_router()
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)


# ---------------------------------------------------------------------------
# Registration (gated by registration_open)
# ---------------------------------------------------------------------------


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
    """JSON login returning {token, user} for legacy clients."""
    from app.services.auth_service import login as svc_login

    cfg = get_or_create_settings(db)
    ip = request.client.host if request.client else None
    return svc_login(db, payload.email, payload.password, cfg, ip)


# ---------------------------------------------------------------------------
# Backward-compat: GET /api/v1/auth/me
# ---------------------------------------------------------------------------


def _to_profile(user: User) -> UserProfile:
    photo_url = f"/uploads/profiles/{user.profile_photo}" if user.profile_photo else None
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        gravatar_hash=user.gravatar_hash,
        is_admin=user.is_admin,
        is_superuser=user.is_superuser,
        language=user.language or "en",
        profile_photo_url=photo_url,
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
def logout_compat():
    """No-op logout for legacy clients (token invalidation is client-side)."""
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

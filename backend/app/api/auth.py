"""Auth endpoints: register, login, me, update profile, logout, delete account."""

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.security import get_optional_user
from app.db.session import get_db
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserProfile
from app.services import auth_service
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=AuthResponse)
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)):
    cfg = get_or_create_settings(db)
    return auth_service.register(db, payload.email, payload.password, cfg, payload.display_name)


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    cfg = get_or_create_settings(db)
    client_ip = request.client.host if request.client else None
    return auth_service.login(db, payload.email, payload.password, cfg, ip_address=client_ip)


@router.get("/me", response_model=UserProfile)
def get_me(
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if user_id is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    return auth_service.get_me(db, user_id)


@router.put("/me", response_model=UserProfile)
async def update_me(
    display_name: str | None = Form(None),
    profile_photo: UploadFile | None = File(None),
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if user_id is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    return await auth_service.update_profile(db, user_id, display_name, profile_photo)


@router.delete("/me", status_code=204)
def delete_me(
    user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if user_id is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    auth_service.delete_account(db, user_id)
    return None


@router.post("/logout", status_code=204)
def logout(response: Response):
    """JWT is stateless; client drops token. Returns 204."""
    return None

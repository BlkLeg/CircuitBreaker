from fastapi_users import schemas
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# FastAPI-Users schemas
# ---------------------------------------------------------------------------


class UserRead(schemas.BaseUser[int]):
    display_name: str | None = None
    gravatar_hash: str | None = None
    is_admin: bool = False
    language: str = "en"
    profile_photo_url: str | None = None


class UserCreate(schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None


# ---------------------------------------------------------------------------
# Legacy schemas (kept for backward compat with bootstrap & frontend)
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    id: int
    email: str
    display_name: str | None = None
    gravatar_hash: str | None = None
    is_admin: bool = False
    is_superuser: bool = False
    language: str = "en"
    profile_photo_url: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: UserProfile


class BootstrapStatusResponse(BaseModel):
    needs_bootstrap: bool
    user_count: int


class BootstrapInitializeRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None
    theme_preset: str
    theme: str | None = "dark"
    timezone: str | None = "UTC"
    language: str | None = "en"
    ui_font: str | None = "inter"
    ui_font_size: str | None = "medium"
    weather_location: str | None = None


class BootstrapThemeResponse(BaseModel):
    preset: str


class BootstrapInitializeResponse(BaseModel):
    token: str
    user: UserProfile
    theme: BootstrapThemeResponse

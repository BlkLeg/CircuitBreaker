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


class VaultResetRequest(BaseModel):
    email: str
    vault_key: str
    new_password: str


class UserProfile(BaseModel):
    id: int
    email: str
    display_name: str | None = None
    gravatar_hash: str | None = None
    is_admin: bool = False
    is_superuser: bool = False
    language: str = "en"
    profile_photo_url: str | None = None
    role: str | None = None  # Phase 6.5: admin | editor | viewer
    scopes: list[str] = []


class AuthResponse(BaseModel):
    token: str
    user: UserProfile
    backup_codes: list[str] | None = None


class BootstrapStatusResponse(BaseModel):
    needs_bootstrap: bool
    user_count: int


class BootstrapInitializeRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None
    theme_preset: str
    api_base_url: str | None = None
    theme: str | None = "dark"
    timezone: str | None = "UTC"
    language: str | None = "en"
    ui_font: str | None = "inter"
    ui_font_size: str | None = "medium"
    weather_location: str | None = None
    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str | None = "Circuit Breaker"
    smtp_tls: bool | None = True


class BootstrapThemeResponse(BaseModel):
    preset: str


class BootstrapInitializeResponse(BaseModel):
    token: str
    user: UserProfile
    theme: BootstrapThemeResponse
    vault_key: str | None = None
    vault_key_warning: bool = False


class BootstrapInitializeOAuthRequest(BaseModel):
    oauth_token: str
    display_name: str | None = None
    theme_preset: str
    api_base_url: str | None = None
    theme: str | None = "dark"
    timezone: str | None = "UTC"
    language: str | None = "en"
    ui_font: str | None = "inter"
    ui_font_size: str | None = "medium"
    weather_location: str | None = None
    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str | None = "Circuit Breaker"
    smtp_tls: bool | None = True

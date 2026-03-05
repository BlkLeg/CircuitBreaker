
from pydantic import BaseModel


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
    is_admin: bool
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

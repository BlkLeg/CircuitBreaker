from fastapi_users import schemas
from pydantic import BaseModel, model_validator

# ---------------------------------------------------------------------------
# FastAPI-Users schemas
# ---------------------------------------------------------------------------


class UserRead(schemas.BaseUser[int]):
    display_name: str | None = None
    gravatar_hash: str | None = None
    is_admin: bool = False
    language: str = "en"
    profile_photo_url: str | None = None
    mfa_enabled: bool = False


class UserCreate(schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None


# ---------------------------------------------------------------------------
# Legacy schemas (kept for backward compat with bootstrap & frontend)
# ---------------------------------------------------------------------------
# Password pre-hash (zero browser leakage): client sends password_hash
# (SHA256(password + salt) hex); server accepts password_hash or legacy password.
# Exactly-one validators ensure one credential form per request.
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str
    password: str | None = None
    password_hash: str | None = None
    display_name: str | None = None

    @model_validator(mode="after")
    def require_password_or_hash(self) -> "RegisterRequest":
        if not self.password and not self.password_hash:
            raise ValueError("Either password or password_hash is required")
        if self.password and self.password_hash:
            raise ValueError("Provide only one of password or password_hash")
        return self


class LoginRequest(BaseModel):
    email: str
    password: str | None = None
    password_hash: str | None = None

    @model_validator(mode="after")
    def require_password_or_hash(self) -> "LoginRequest":
        if not self.password and not self.password_hash:
            raise ValueError("Either password or password_hash is required")
        if self.password and self.password_hash:
            raise ValueError("Provide only one of password or password_hash")
        return self


class VaultResetRequest(BaseModel):
    email: str
    vault_key: str
    new_password: str | None = None
    new_password_hash: str | None = None

    @model_validator(mode="after")
    def require_new_password_or_hash(self) -> "VaultResetRequest":
        if not self.new_password and not self.new_password_hash:
            raise ValueError("Either new_password or new_password_hash is required")
        if self.new_password and self.new_password_hash:
            raise ValueError("Provide only one of new_password or new_password_hash")
        return self


class UserProfile(BaseModel):
    id: int
    email: str
    display_name: str | None = None
    gravatar_hash: str | None = None
    is_admin: bool = False
    is_superuser: bool = False
    language: str = "en"
    profile_photo_url: str | None = None
    mfa_enabled: bool = False
    role: str | None = None  # Phase 6.5: admin | editor | viewer
    scopes: list[str] = []


class AuthResponse(BaseModel):
    token: str
    user: UserProfile
    backup_codes: list[str] | None = None


class BootstrapStatusResponse(BaseModel):
    needs_bootstrap: bool
    user_count: int
    client_hash_salt: str = "circuitbreaker-salt-v1"


# Onboarding (OOBE) step state — public API, no auth required
ONBOARDING_STEPS = frozenset(
    {"start", "account", "theme", "regional", "email", "summary", "finish"}
)


class OnboardingStepResponse(BaseModel):
    current_step: str
    previous_step: str


class OnboardingStepUpdateRequest(BaseModel):
    step: str

    @model_validator(mode="after")
    def step_must_be_valid(self) -> "OnboardingStepUpdateRequest":
        if self.step not in ONBOARDING_STEPS:
            raise ValueError(f"step must be one of {sorted(ONBOARDING_STEPS)}")
        return self


class BootstrapInitializeRequest(BaseModel):
    email: str
    password: str | None = None
    password_hash: str | None = None
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

    @model_validator(mode="after")
    def require_password_or_hash(self) -> "BootstrapInitializeRequest":
        if not self.password and not self.password_hash:
            raise ValueError("Either password or password_hash is required")
        if self.password and self.password_hash:
            raise ValueError("Provide only one of password or password_hash")
        return self


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

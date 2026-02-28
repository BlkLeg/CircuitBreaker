import re
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import json
import logging

_logger = logging.getLogger(__name__)

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


class BrandingConfig(BaseModel):
    app_name: str = "Circuit Breaker"
    favicon_path: Optional[str] = None
    login_logo_path: Optional[str] = None
    primary_color: str = "#00d4ff"
    accent_colors: list[str] = ["#ff6b6b", "#4ecdc4"]

    @field_validator("primary_color")
    @classmethod
    def validate_primary_color(cls, v: str) -> str:
        if not _HEX_RE.match(v):
            raise ValueError(f"primary_color must be a valid 6-digit hex color (e.g. #00d4ff), got: {v!r}")
        return v

    @field_validator("accent_colors")
    @classmethod
    def validate_accent_colors(cls, v: list) -> list:
        if not (1 <= len(v) <= 4):
            raise ValueError("accent_colors must contain 1–4 colors")
        for color in v:
            if not _HEX_RE.match(color):
                raise ValueError(f"accent_colors: {color!r} is not a valid 6-digit hex color")
        return v

    @field_validator("app_name")
    @classmethod
    def validate_app_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("app_name cannot be empty")
        if len(v) > 100:
            raise ValueError("app_name must be 100 characters or fewer")
        return v


VALID_PRESETS = {
    "cyberpunk-neon", "dark-matter", "solarized-dark", "nord",
    "dracula", "gruvbox-dark", "monokai", "one-dark", "custom",
}


class ThemeColors(BaseModel):
    """Per-mode color map.  All fields are optional so partial custom themes are
    accepted without 422 errors.  ``gridLine`` may be an rgba(...) string.
    This model is used for documentation; at runtime ``AppSettingsUpdate`` /
    ``AppSettingsRead`` accept/return a raw ``dict`` to support the structured
    ``{dark: {...}, light: {...}}`` format sent by the frontend."""

    primary: Optional[str] = None
    secondary: Optional[str] = None
    accent1: Optional[str] = None
    accent2: Optional[str] = None
    background: Optional[str] = None
    surface: Optional[str] = None
    surfaceAlt: Optional[str] = None
    border: Optional[str] = None
    text: Optional[str] = None
    textMuted: Optional[str] = None
    gridLine: Optional[str] = None  # may be rgba(…), not necessarily hex


class AppSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    theme: str
    default_environment: Optional[str] = None
    show_experimental_features: bool
    api_base_url: Optional[str] = None
    map_default_filters: Optional[str] = None  # JSON string
    vendor_icon_mode: str
    environments: list[str] = ["prod", "staging", "dev"]
    categories: list[str] = []
    locations: list[str] = []
    dock_order: Optional[list[str]] = None
    dock_hidden_items: Optional[list[str]] = None
    show_page_hints: bool = True
    auth_enabled: bool = False
    session_timeout_hours: int = 24
    # Advanced Theming
    theme_preset: str = "cyberpunk-neon"
    custom_colors: Optional[str] = Field(default=None, exclude=True)  # raw JSON from ORM
    theme_colors: Optional[Any] = None  # parsed in model_validator below — flat or {dark,light} dict
    # Flat branding columns — read from ORM but excluded from JSON output (nested via `branding`)
    app_name: str = Field(default="Circuit Breaker", exclude=True)
    favicon_path: Optional[str] = Field(default=None, exclude=True)
    login_logo_path: Optional[str] = Field(default=None, exclude=True)
    primary_color: str = Field(default="#00d4ff", exclude=True)
    accent_colors: Optional[str] = Field(default='["#ff6b6b","#4ecdc4"]', exclude=True)
    # Nested branding object (computed in model_validator)
    branding: BrandingConfig = BrandingConfig()
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def build_branding(self) -> 'AppSettingsRead':
        raw_accents = self.accent_colors
        if isinstance(raw_accents, str):
            try:
                accent_colors = json.loads(raw_accents)
            except Exception:
                accent_colors = ["#ff6b6b", "#4ecdc4"]
        elif raw_accents is None:
            accent_colors = ["#ff6b6b", "#4ecdc4"]
        else:
            accent_colors = raw_accents
        self.branding = BrandingConfig(
            app_name=self.app_name or 'Circuit Breaker',
            favicon_path=self.favicon_path,
            login_logo_path=self.login_logo_path,
            primary_color=self.primary_color or '#00d4ff',
            accent_colors=accent_colors,
        )
        return self

    @model_validator(mode='after')
    def build_theme_colors(self) -> 'AppSettingsRead':
        raw = self.custom_colors
        if raw:
            try:
                # Return raw dict as-is — may be flat {primary,…} or structured {dark:{…},light:{…}}
                self.theme_colors = json.loads(raw)
            except Exception:
                pass
        return self

    @field_validator('environments', mode='before')
    @classmethod
    def parse_environments(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'environments' setting, using default. Error: %s", exc)
                return ["prod", "staging", "dev"]
        if v is None:
            return ["prod", "staging", "dev"]
        return v

    @field_validator('categories', mode='before')
    @classmethod
    def parse_categories(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'categories' setting, using default. Error: %s", exc)
                return []
        if v is None:
            return []
        return v

    @field_validator('locations', mode='before')
    @classmethod
    def parse_locations(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'locations' setting, using default. Error: %s", exc)
                return []
        if v is None:
            return []
        return v

    @field_validator('dock_order', mode='before')
    @classmethod
    def parse_dock_order(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'dock_order' setting, using default. Error: %s", exc)
                return None
        return v

    @field_validator('dock_hidden_items', mode='before')
    @classmethod
    def parse_dock_hidden_items(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'dock_hidden_items' setting, using default. Error: %s", exc)
                return None
        return v


class AppSettingsUpdate(BaseModel):
    theme: Optional[Literal["auto", "dark", "light"]] = None
    default_environment: Optional[str] = None
    show_experimental_features: Optional[bool] = None
    api_base_url: Optional[str] = None
    map_default_filters: Optional[Any] = None  # accepts dict or None; serialized to JSON string
    vendor_icon_mode: Optional[Literal["none", "built_in", "custom_files"]] = None
    environments: Optional[list[str]] = None
    categories: Optional[list[str]] = None
    locations: Optional[list[str]] = None
    dock_order: Optional[list[str]] = None
    dock_hidden_items: Optional[list[str]] = None
    show_page_hints: Optional[bool] = None
    auth_enabled: Optional[bool] = None
    session_timeout_hours: Optional[int] = None
    branding: Optional[BrandingConfig] = None
    theme_preset: Optional[str] = None
    # Accepts a flat {primary,…} dict OR the frontend's structured {dark:{…},light:{…}} object.
    theme_colors: Optional[dict[str, Any]] = None

    @field_validator("theme_preset")
    @classmethod
    def validate_preset(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PRESETS:
            raise ValueError(f"theme_preset must be one of {sorted(VALID_PRESETS)}")
        return v

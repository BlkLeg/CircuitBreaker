import json
import logging
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_logger = logging.getLogger(__name__)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandingConfig(BaseModel):
    app_name: str = "Circuit Breaker"
    favicon_path: str | None = None
    login_logo_path: str | None = None
    login_bg_path: str | None = None
    primary_color: str = "#fe8019"
    accent_colors: list[str] = ["#fabd2f", "#b8bb26"]

    @field_validator("primary_color")
    @classmethod
    def validate_primary_color(cls, v: str) -> str:
        if not _HEX_RE.match(v):
            raise ValueError(
                f"primary_color must be a valid 6-digit hex color (e.g. #fe8019), got: {v!r}"
            )
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
    "cyberpunk-neon",
    "dark-matter",
    "solarized-dark",
    "nord",
    "dracula",
    "gruvbox-dark",
    "monokai",
    "one-dark",
    "custom",
    # theme.park vendored palettes
    "tp-maroon",
    "tp-hotline",
    "tp-aquamarine",
    "tp-space-gray",
    "tp-hotpink",
    "tp-overseer",
}


class ThemeColors(BaseModel):
    """Per-mode color map.  All fields are optional so partial custom themes are
    accepted without 422 errors.  ``gridLine`` may be an rgba(...) string.
    This model is used for documentation; at runtime ``AppSettingsUpdate`` /
    ``AppSettingsRead`` accept/return a raw ``dict`` to support the structured
    ``{dark: {...}, light: {...}}`` format sent by the frontend."""

    primary: str | None = None
    secondary: str | None = None
    accent1: str | None = None
    accent2: str | None = None
    background: str | None = None
    surface: str | None = None
    surfaceAlt: str | None = None
    border: str | None = None
    text: str | None = None
    textMuted: str | None = None
    gridLine: str | None = None  # may be rgba(…), not necessarily hex


class AppSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    theme: str
    default_environment: str | None = None
    show_experimental_features: bool
    api_base_url: str | None = None
    map_default_filters: str | None = None  # JSON string
    vendor_icon_mode: str
    environments: list[str] = ["prod", "staging", "dev"]
    categories: list[str] = []
    locations: list[str] = []
    dock_order: list[str] | None = None
    dock_hidden_items: list[str] | None = None
    show_page_hints: bool = True
    show_header_widgets: bool = True
    show_time_widget: bool = True
    show_weather_widget: bool = True
    weather_location: str = "Phoenix, AZ"
    auth_enabled: bool = False
    registration_open: bool = True
    rate_limit_profile: str = "normal"
    session_timeout_hours: int = 24
    dev_mode: bool = False
    audit_log_retention_days: int = 90
    audit_log_hide_ip: bool = False
    show_external_nodes_on_map: bool = True
    timezone: str = "UTC"
    language: str = "en"
    # Auto-Discovery
    discovery_enabled: bool = False
    discovery_auto_merge: bool = False
    discovery_default_cidr: str = ""
    discovery_nmap_args: str = "-sV -O --open -T4"
    discovery_snmp_community: str = Field(default="", exclude=True)
    discovery_schedule_cron: str = ""
    discovery_http_probe: bool = True
    discovery_retention_days: int = 30
    scan_ack_accepted: bool = False
    # Font preferences
    ui_font: str = "inter"
    ui_font_size: str = "medium"
    # Advanced Theming
    theme_preset: str = "gruvbox-dark"
    custom_colors: str | None = Field(default=None, exclude=True)  # raw JSON from ORM
    theme_colors: Any | None = None  # parsed in model_validator below — flat or {dark,light} dict
    # Flat branding columns — read from ORM but excluded from JSON output (nested via `branding`)
    app_name: str = Field(default="Circuit Breaker", exclude=True)
    favicon_path: str | None = Field(default=None, exclude=True)
    login_logo_path: str | None = Field(default=None, exclude=True)
    login_bg_path: str | None = Field(default=None, exclude=True)
    primary_color: str = Field(default="#fe8019", exclude=True)
    accent_colors: str | None = Field(default='["#fabd2f","#b8bb26"]', exclude=True)
    # Nested branding object (computed in model_validator)
    branding: BrandingConfig = BrandingConfig()
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def build_branding(self) -> "AppSettingsRead":
        raw_accents = self.accent_colors
        if isinstance(raw_accents, str):
            try:
                accent_colors = json.loads(raw_accents)
            except Exception:
                accent_colors = ["#fabd2f", "#b8bb26"]
        elif raw_accents is None:
            accent_colors = ["#fabd2f", "#b8bb26"]
        else:
            accent_colors = raw_accents
        self.branding = BrandingConfig(
            app_name=self.app_name or "Circuit Breaker",
            favicon_path=self.favicon_path,
            login_logo_path=self.login_logo_path,
            login_bg_path=self.login_bg_path,
            primary_color=self.primary_color or "#fe8019",
            accent_colors=accent_colors,
        )
        return self

    @model_validator(mode="after")
    def build_theme_colors(self) -> "AppSettingsRead":
        raw = self.custom_colors
        if raw:
            try:
                # Return raw dict as-is — may be flat {primary,…} or structured {dark:{…},light:{…}}
                self.theme_colors = json.loads(raw)
            except Exception:
                pass
        return self

    @field_validator("environments", mode="before")
    @classmethod
    def parse_environments(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning(
                    "Failed to parse 'environments' setting, using default. Error: %s", exc
                )
                return ["prod", "staging", "dev"]
        if v is None:
            return ["prod", "staging", "dev"]
        return v

    @field_validator("categories", mode="before")
    @classmethod
    def parse_categories(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning(
                    "Failed to parse 'categories' setting, using default. Error: %s", exc
                )
                return []
        if v is None:
            return []
        return v

    @field_validator("locations", mode="before")
    @classmethod
    def parse_locations(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning(
                    "Failed to parse 'locations' setting, using default. Error: %s", exc
                )
                return []
        if v is None:
            return []
        return v

    @field_validator("dock_order", mode="before")
    @classmethod
    def parse_dock_order(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning(
                    "Failed to parse 'dock_order' setting, using default. Error: %s", exc
                )
                return None
        return v

    @field_validator("dock_hidden_items", mode="before")
    @classmethod
    def parse_dock_hidden_items(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning(
                    "Failed to parse 'dock_hidden_items' setting, using default. Error: %s", exc
                )
                return None
        return v


class AppSettingsUpdate(BaseModel):
    theme: Literal["auto", "dark", "light"] | None = None
    default_environment: str | None = None
    show_experimental_features: bool | None = None
    api_base_url: str | None = None
    map_default_filters: Any | None = None  # accepts dict or None; serialized to JSON string
    vendor_icon_mode: Literal["none", "built_in", "custom_files"] | None = None
    environments: list[str] | None = None
    categories: list[str] | None = None
    locations: list[str] | None = None
    dock_order: list[str] | None = None
    dock_hidden_items: list[str] | None = None
    show_page_hints: bool | None = None
    show_header_widgets: bool | None = None
    show_time_widget: bool | None = None
    show_weather_widget: bool | None = None
    weather_location: str | None = None
    auth_enabled: bool | None = None
    registration_open: bool | None = None
    rate_limit_profile: Literal["relaxed", "normal", "strict"] | None = None
    session_timeout_hours: int | None = None
    dev_mode: bool | None = None
    audit_log_retention_days: int | None = None
    audit_log_hide_ip: bool | None = None
    branding: BrandingConfig | None = None
    theme_preset: str | None = None
    show_external_nodes_on_map: bool | None = None
    timezone: str | None = None
    language: Literal["en", "es", "fr", "de", "zh", "ja"] | None = None
    # Auto-Discovery
    discovery_enabled: bool | None = None
    discovery_auto_merge: bool | None = None
    discovery_default_cidr: str | None = None
    discovery_nmap_args: str | None = None
    discovery_snmp_community: str | None = None
    discovery_schedule_cron: str | None = None
    discovery_http_probe: bool | None = None
    discovery_retention_days: int | None = None
    scan_ack_accepted: bool | None = None
    # Font preferences
    ui_font: str | None = None
    ui_font_size: str | None = None
    # Accepts a flat {primary,…} dict OR the frontend's structured {dark:{…},light:{…}} object.
    theme_colors: dict[str, Any] | None = None

    @field_validator("theme_preset")
    @classmethod
    def validate_preset(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_PRESETS:
            raise ValueError(f"theme_preset must be one of {sorted(VALID_PRESETS)}")
        return v

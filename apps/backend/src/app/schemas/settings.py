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
    map_default_filters: dict | None = None  # JSONB; may arrive as string from legacy writes
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
    auth_enabled: bool = True
    registration_open: bool = True
    rate_limit_profile: str = "normal"
    session_timeout_hours: int = 24
    # Phase 6.5: User management
    concurrent_sessions: int = 5
    login_lockout_attempts: int = 5
    login_lockout_minutes: int = 15
    invite_expiry_days: int = 7
    masquerade_enabled: bool = True
    auto_monitor_on_discovery: bool = False
    dev_mode: bool = False
    audit_log_retention_days: int = 90
    audit_log_hide_ip: bool = False
    db_backup_retention_days: int = 30
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
    max_concurrent_scans: int = 2
    # Safe discovery mode
    discovery_mode: str = "safe"
    docker_discovery_enabled: bool = False
    docker_socket_path: str = "/var/run/docker.sock"
    docker_sync_interval_minutes: int = 5
    graph_default_layout: str = "dagre"
    map_title: str = "Topology"
    graph_uplink_overrides: dict = {}  # nodeId -> Mbps for non-hardware nodes
    # Font preferences
    ui_font: str = "inter"
    ui_font_size: str = "medium"
    # CVE sync
    cve_sync_enabled: bool = False
    cve_sync_interval_hours: int = 24
    cve_last_sync_at: str | None = None
    # Phase 3: Realtime / NATS
    realtime_notifications_enabled: bool = True
    realtime_transport: str = "auto"  # "auto" | "sse" | "websocket"
    # Phase 4: Discovery Engine 2.0
    listener_enabled: bool = False
    prober_interval_minutes: int = 15
    deep_dive_max_parallel: int = 5
    scan_aggressiveness: str = "normal"  # low | normal | high
    mdns_enabled: bool = True
    ssdp_enabled: bool = True
    arp_enabled: bool = True
    tcp_probe_enabled: bool = True
    # Mobile / phone discovery
    mobile_discovery_enabled: bool = True
    mdns_multicast_enabled: bool = True
    mdns_listener_duration: int = 8
    dhcp_lease_file_path: str = ""
    dhcp_router_host: str = ""
    dhcp_router_user_enc: str | None = Field(default=None, exclude=True)  # never returned
    dhcp_router_pass_enc: str | None = Field(default=None, exclude=True)  # never returned
    dhcp_router_command: str = "cat /var/lib/misc/dnsmasq.leases"
    dhcp_router_credentials_set: bool = False  # computed in model_validator
    # v0.2.0: Self-aware cluster topology
    self_cluster_enabled: bool = False
    # SMTP / Email delivery
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password_enc: str | None = Field(
        default=None, exclude=True
    )  # never returned; use smtp_password_set
    smtp_password_set: bool = False  # computed in model_validator
    smtp_from_email: str = ""
    smtp_from_name: str = "Circuit Breaker"
    smtp_tls: bool = True
    smtp_last_test_at: str | None = None
    smtp_last_test_status: str | None = None
    # Advanced Theming
    theme_preset: str = "gruvbox-dark"
    custom_colors: dict | str | None = Field(default=None, exclude=True)  # raw JSON from ORM
    theme_colors: Any | None = None  # parsed in model_validator below — flat or {dark,light} dict
    # Flat branding columns — read from ORM but excluded from JSON output (nested via `branding`)
    app_name: str = Field(default="Circuit Breaker", exclude=True)
    favicon_path: str | None = Field(default=None, exclude=True)
    login_logo_path: str | None = Field(default=None, exclude=True)
    login_bg_path: str | None = Field(default=None, exclude=True)
    primary_color: str = Field(default="#fe8019", exclude=True)
    accent_colors: list | str | None = Field(default=None, exclude=True)
    # Nested branding object (computed in model_validator)
    branding: BrandingConfig = BrandingConfig()
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def build_smtp_password_set(self) -> "AppSettingsRead":
        self.smtp_password_set = bool(self.smtp_password_enc)
        self.dhcp_router_credentials_set = bool(
            self.dhcp_router_user_enc or self.dhcp_router_pass_enc
        )
        return self

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
        if isinstance(raw, dict):
            self.theme_colors = raw
        elif raw:
            try:
                # Return raw dict as-is — may be flat {primary,…} or structured {dark:{…},light:{…}}
                self.theme_colors = json.loads(raw)
            except Exception:
                pass
        return self

    @field_validator("graph_uplink_overrides", mode="before")
    @classmethod
    def default_uplink_overrides(cls, v: Any) -> dict:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {}

    @field_validator("map_default_filters", mode="before")
    @classmethod
    def parse_map_default_filters(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return None
        return v

    @field_validator("environments", mode="before")
    @classmethod
    def parse_environments(cls, v: Any) -> Any:
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
    def parse_categories(cls, v: Any) -> Any:
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
    def parse_locations(cls, v: Any) -> Any:
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
    def parse_dock_order(cls, v: Any) -> Any:
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
    def parse_dock_hidden_items(cls, v: Any) -> Any:
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
    registration_open: bool | None = None
    rate_limit_profile: Literal["relaxed", "normal", "strict"] | None = None
    session_timeout_hours: int | None = None
    # Phase 6.5: User management
    concurrent_sessions: int | None = None
    login_lockout_attempts: int | None = None
    login_lockout_minutes: int | None = None
    invite_expiry_days: int | None = None
    masquerade_enabled: bool | None = None
    auto_monitor_on_discovery: bool | None = None
    dev_mode: bool | None = None
    audit_log_retention_days: int | None = None
    audit_log_hide_ip: bool | None = None
    db_backup_retention_days: int | None = None
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
    max_concurrent_scans: int | None = None
    # Safe discovery mode
    discovery_mode: Literal["safe", "full"] | None = None
    docker_discovery_enabled: bool | None = None
    docker_socket_path: str | None = None
    docker_sync_interval_minutes: int | None = None
    graph_default_layout: str | None = None
    map_title: str | None = None
    graph_uplink_overrides: dict | None = None
    # Font preferences
    ui_font: str | None = None
    ui_font_size: str | None = None
    # CVE sync
    cve_sync_enabled: bool | None = None
    cve_sync_interval_hours: int | None = None
    # Phase 3: Realtime / NATS
    realtime_notifications_enabled: bool | None = None
    realtime_transport: str | None = None
    # Phase 4: Discovery Engine 2.0
    listener_enabled: bool | None = None
    prober_interval_minutes: int | None = None
    deep_dive_max_parallel: int | None = None
    scan_aggressiveness: str | None = None
    mdns_enabled: bool | None = None
    ssdp_enabled: bool | None = None
    arp_enabled: bool | None = None
    tcp_probe_enabled: bool | None = None
    # v0.2.0: Self-aware cluster topology
    self_cluster_enabled: bool | None = None
    # SMTP / Email delivery
    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None  # plaintext → encrypted by settings_service before storing
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None
    smtp_tls: bool | None = None
    # Accepts a flat {primary,…} dict OR the frontend's structured {dark:{…},light:{…}} object.
    theme_colors: dict[str, Any] | None = None
    # Mobile / phone discovery
    mobile_discovery_enabled: bool | None = None
    mdns_multicast_enabled: bool | None = None
    mdns_listener_duration: int | None = None
    dhcp_lease_file_path: str | None = None
    dhcp_router_host: str | None = None
    dhcp_router_username: str | None = None  # plaintext → encrypted on write
    dhcp_router_password: str | None = None  # plaintext → encrypted on write
    dhcp_router_command: str | None = None

    @field_validator("theme_preset")
    @classmethod
    def validate_preset(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_PRESETS:
            raise ValueError(f"theme_preset must be one of {sorted(VALID_PRESETS)}")
        return v


class SmtpUpdate(BaseModel):
    """SMTP-only update payload – subset of AppSettingsUpdate."""

    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None  # plaintext → encrypted by settings_service
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None
    smtp_tls: bool | None = None
